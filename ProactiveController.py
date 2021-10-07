#!/usr/bin/python

from ryu import cfg
from threading import Timer
from topo_discovery.api import get_switch

import OFP_Helper
from ShortestPath.dijkstra_te import Graph
import ShortestPath.protection_path_computation as ppc
from TopoDiscoveryController import TopoDiscoveryController


class ProactiveController(TopoDiscoveryController):
    """ Ryu proactive controller that implements protection recovery. For each host
    pair multiple paths are computed and installed onto switches using the fast-failover
    group type. When failurs occur switches will recover without controller involvment.
    If 'optimise_protection' config attribute is set to True, controller recomputes paths
    after several seconds of topology modification (triggered by a failure).

    Note:
        A path consolidation mechanism is used to delay path computation to allow topo
    to stabilise. Each host-dest pair will have a primary, minimally overlapping secondary
    and path splices. A path splice is the shortest path from a unique node in the primary
    to a unique node in the secondary, such that traffic can swap back and forth. On ingress
    traffic is VLAN taged with a GID to identify the path it belongs to. Tags are removed on
    egress.

    Attributres:
        LOOSE_SPLICE (bool): Static attribute that specifies if loose (true)
            or strict (false) path splices will be computed.
        CONF (oslo_config.cfg): Congif object that contains attributes
    """
    CONTROLLER_NAME = "PROACTIVE"
    LOOSE_SPLICE = False        # COMPUTE STRICT PATH SPLICES


    def __init__(self, *args, **kwargs):
        """ Initiate the controller. """
        super(ProactiveController, self).__init__(*args, **kwargs)
        self.__topo_timer = None
        self.paths = {}

        self.CONF.register_opts([
            cfg.BoolOpt("optimise_protection",
                default=True,
                help="Optimise protection paths when failure occur")
        ], group="application")

        self.logger.info("optimise_protection: %s" % self.CONF.application.optimise_protection)
        self.register_cleanup(self.__stop_cleanup)


    def __stop_cleanup(self):
        """ Callback handler that closes local timers and instances """
        if self.__topo_timer is not None:
            self.__topo_timer.cancel()


    # -------------------------- HELPER METHODS --------------------------


    def topo_changed(self):
        """ Topo change occured so trigger/reset path computation timer """
        if self.__topo_timer is not None:
            self.__topo_timer.cancel()

        self.__topo_timer = Timer(2, self._install_protection)
        self.__topo_timer.start()


    def _install_protection(self):
        """ Compute and install protection paths between hosts `:cls:attr:(hosts)` using the
        fast-failover scheme. Each src-dest pair will get a unique VID / GID (see ``_get_gid()``).
        Bridges that connect to hosts are ingress or egress and push and pop VLAN tags. VLAN tags
        are used to identify what path traffic belongs to.
        """
        # Do not compute if state rebuild in progress or controller is not master
        if self._rebuild_state_in_progress():
            self.logger.info("State rebuild in progress, resetting timer!")
            self._rebuild_state_tick()
            self.topo_changed()
            return

        if not self.is_master():
            self.logger.info("Controller is not a master, do not compute anything")
            return

        # Send the new topology to the root controller
        self.__topo_timer = None
        self.ctrl_com.send_topo()
        self.logger.info("----------COMPUTING PATHS----------")

        # If no host pairs exist remove old installed paths
        if len(self.hosts) < 2 and len(self.paths) > 0:
            self.logger.info("No longer have host pairs, removing old paths")
            for (hkey, info) in self.paths.items():
                # Do not remove inter-domain paths
                if (info["ingress"] is None or info["egress"] is None or
                        isinstance(info["ingress"], tuple) or
                        isinstance(info["egress"], tuple)):
                    continue
                self._compute_paths(self.graph, None, None, None, None, path_key=hkey)
            return

        for host_1 in self.hosts:
            for host_2 in self.hosts:
                if host_1 == host_2:
                    continue

                graph = Graph(self.graph.topo)
                addr = self.graph.get_port_info(host_2, -1)
                dest_addr = addr["address"]
                dest_eth = addr["eth_address"]
                self._compute_paths(graph, host_1, host_2, dest_addr, dest_eth)


    def add_dummy_destination(self, hkey, info, graph):
        """ Add dummy destinations to inter-domain links to allow computation of
        path segments. The method will modify the topology `graph` object to contain
        dummy destination nodes on other end of inter-domain links. Dummy nodes
        take the format 'TARGET<n>' where n is the index of the instruction in `info`.

        Args:
            hkey (str, str): Host pair key of path
            info (list): List of inter-domain path instructions
            graph (Graph): Topology object to use for path computation
        """
        host_1, host_2 = hkey
        ret_target = []
        if host_2 in self.hosts and host_1 not in self.hosts:
            # If this is a destination segment the target is the destination
            for i in range(len(info)):
                ret_target.append(host_2)
        else:
            # XXX: If multiple instructions have the same output ports, method will break
            # path computation as only the final target name exists in the graph (overwrites
            # the previous injected targets). To fix this we need to keep track of the output
            # ports that were over-written. If multiple lead to the same just return that target
            rewrote_out = {}

            # Otherwise add a fake name to the end of the graph
            for i in range(len(info)):
                fake_name = "TARGET%s" % i
                out_sw = info[i]["out"][0]
                out_port = info[i]["out"][1]

                # XXX: Fix for multiple instructions using same link
                if info[i]["out"] in rewrote_out:
                    ret_target.append(rewrote_out[info[i]["out"]])
                    continue

                rewrote_out[info[i]["out"]] = fake_name
                graph.topo[out_sw][out_port]["dest"] = fake_name
                graph.topo_stale = True
                ret_target.append(fake_name)
        return ret_target


    def compute_path_segment_secondary_paths(self, hkey, info, target_names, graph):
        """ Compute and return the secondary paths for a inter-domain path based on
        received inter-domain path instructions `info`. Method will compute path
        segments for all backup paths, returning the group table, special flow
        table and ingress change ports that need to be applied when installing the
        path segment onto the switches.

        Args:
            hkey (str, str): Host pair key of path
            info (list of dict): Inter-domain path instruction received from root
                controller to compute path segment for src-dest pair `hkey`. First
                element of list denotes primary path (ignored) while any subsequent
                elements are the backup paths that will be processed by this method.
                List will contain at-lest a single element.
            target_names (list of str): List of fake nodes introduced in graph to
                compute path segmenents that use a particular egress port.
            graph (Graph): Topology object to use for path computation

        Returns:
            (dict, dict, list): Dictionary of secondary path group tables, special flows
                and list of ingress change detection ports to apply when installing
                path segment (and computing primary path).
        """
        host_1 = hkey[0]
        host_2 = hkey[1]
        gp = {}
        special_flows = {}
        ingress_change_ports = []

        # If the action instruction is delete do not compute anything
        if info[0]["action"] == "delete":
            return gp, special_flows, ingress_change_ports

        # Is this the start segment (source host)?
        if host_1 in self.hosts:
            for i in range(1, len(info)):
                target = target_names[i]
                g = Graph(graph.topo)
                dict = self.compute_path_dict(g, host_1, target, path_key=hkey)
                self.__combine_table(gp, dict["groups"])
                self.__combine_table(special_flows, dict["special_flows"])

        # Is this the end segment (destination host)?
        elif host_2 in self.hosts:
            for i in range(1, len(info)):
                # XXX: Can also use target_names array as method checks if
                # host_2 is in the hosts list. If it is will make the array
                # return the host_2 value. Regardless, force host_2 to be
                # sure path info is correct
                #target = target_names[i]
                target = host_2
                g = Graph(graph.topo)
                dict = self.compute_path_dict(g, info[i]["in"][0], target, path_key=hkey)
                self.__combine_table(gp, dict["groups"])
                self.__combine_table(special_flows, dict["special_flows"])

                # Add the in port to the list of ingress change detection ports
                # if different from the primary instruction port
                if (info[i]["in"] not in ingress_change_ports and
                        info[i]["in"] != info[0]["in"]):
                    ingress_change_ports.append(info[i]["in"])

        # Otherwise assume this is an intermediate domain to domain segment
        else:
            if not isinstance(info[0]["in"], tuple) or not isinstance(info[0]["out"], tuple):
                self.logger.error("Intermediat path dosen't contain tuple in and or out values!")
                return

            # Compute the extra group trable for the secondary path(s)
            for i in range(1, len(info)):
                target = target_names[i]
                g = Graph(graph.topo)
                dict = self.compute_path_dict(g, info[i]["in"][0], target, path_key=hkey)
                self.__combine_table(gp, dict["groups"])
                self.__combine_table(special_flows, dict["special_flows"])

                # Add the in port to the list of ingress change detection ports
                # if different from the primary instruction port
                if (info[i]["in"] not in ingress_change_ports and
                        info[i]["in"] != info[0]["in"]):
                    ingress_change_ports.append(info[i]["in"])

        return gp, special_flows, ingress_change_ports


    def compute_path_segment(self, hkey, info):
        """ Compute and install an path segment from a list of root controller
        inter-domain path instructions. If the action of the first instruction
        is "delete" any exiting inter-domain path segment for the current `hkey`
        is uninstalled. Method computes the primary path of the segment based
        on the first object in the instruction list and calls
        ``compute_path_segment_secondary_path`` to compute all other backup
        paths (remaining elements of list). Fake nodes are added to a copy of
        the current topology by calling ``add_dummy_destinations`` to ensure
        that the computed path use the specified egress port of the instruction
        object.

        Args:
            hkey (str, str): Host pair key of path
            info (list of dict): Inter-domain path instructions received from
                root controller for src-dest pair `hkey`. First element of list
                is the primary path while subsequent elements are backup paths.
        """
        # Do not compute paths if we are not a master controller
        if not self.is_master():
            self.logger.info("Controller is not a master, do not compute anything")
            return

        host_1 = hkey[0]
        host_2 = hkey[1]
        graph = Graph(self.graph.topo)
        pinfo = {}
        if hkey in self.paths:
            pinfo = self.paths[hkey]

        # If the action is delete uninstall any existing path for src-dest pair and
        # remove ingress change detection rules (if installed)
        if info[0]["action"] == "delete":
            if "ingress_change_detect" in pinfo:
                for ing in pinfo["ingress_change_detect"]:
                    self.__delete_ingress_change_detect_rule(ing[1], pinfo["gid"], dpid=ing[0])
            self._compute_paths(graph, None, None, None, None, path_key=hkey)
            return

        # Add fake nodes to the topology and compute secondary path segments
        target_names = self.add_dummy_destination(hkey, info, graph)
        gp, special_flows, ingress_change_ports = self.compute_path_segment_secondary_paths(
                                                    hkey, info, target_names, graph)

        # Is this the start segment (source host)?
        if host_1 in self.hosts:
            target = target_names[0]
            dest_addr = info[0]["out_addr"]
            dest_eth = None
            self._compute_paths(graph, host_1, target, dest_addr, dest_eth, inp=info[0]["in"],
                                    outp=info[0]["out"], path_key=hkey, combine_gp=gp,
                                    combine_special_flows=special_flows)

        # Is this the end segment (destination host)?
        elif host_2 in self.hosts:
            # XXX: Can also use target_names array as method checks if
            # host_2 is in the hosts list. If it is will make the array
            # return the host_2 value. Regardless, force host_2 to be
            # sure path info is correct
            #target = target_names[i]
            target = host_2
            dest_addr = None
            dest_eth = info[0]["out_eth"]
            self._compute_paths(graph, info[0]["in"][0], target, dest_addr, dest_eth, inp=info[0]["in"],
                                    outp=info[0]["out"], path_key=hkey, combine_gp=gp,
                                    combine_special_flows=special_flows)

        # Otherwise assume this is an intermediate domain to domain segment
        else:
            if not isinstance(info[0]["in"], tuple) or not isinstance(info[0]["out"], tuple):
                self.logger.error("Intermediat path dosen't contain tuple in and or out values!")
                return

            target = target_names[0]
            dest_addr = None
            dest_eth = None
            self._compute_paths(graph, info[0]["in"][0], target, dest_addr, dest_eth, inp=info[0]["in"],
                                    outp=info[0]["out"], path_key=hkey, combine_gp=gp,
                                    combine_special_flows=special_flows)

        # Remove all ingress change detection rules if we now only have a single
        # inter-domain path instruction (and rules instaled)
        if len(info) == 1:
            if "ingress_change_detect" in pinfo and len(pinfo["ingress_change_detect"]) > 0:
                self.logger.info("Path %s-%s has no alterantive, rem old ingress change rules" % (hkey))
                for ing in pinfo["ingress_change_detect"]:
                    self.__delete_ingress_change_detect_rule(ing[1], pinfo["gid"], dpid=ing[0])
        else:
            # Remove any old ingress change locations that no longer exist
            if "ingress_change_detect" in pinfo:
                for ing in pinfo["ingress_change_detect"]:
                    if ing not in ingress_change_ports:
                        self.__delete_ingress_change_detect_rule(ing[1], pinfo["gid"], dpid=ing[0])

            # Install the new ingress change rules
            for ing in ingress_change_ports:
                if "ingress_change_detect" in pinfo and ing in pinfo["ingress_change_detect"]:
                    continue
                self.__install_ingress_change_detect_rule(ing[1], hkey, dpid=ing[0])

            # Update the path info ingress change detection installed rules
            self.paths[hkey]["ingress_change_detect"] = ingress_change_ports


    def compute_path_dict(self, graph, src, dest, inp=None, outp=None, path_key=None, graph_sec=None):
        """ Compute and generate a path info dictionary from `src` to `dest` using the topology
        `graph`. Method computes primary, secondary and path splices. All path info is translated
        into an enriched path dictionary that defines path details. Returned dictionary contains
        the primary, secondary and splice path node lists which should be removed.

        Args:
            graph (Graph): Topology object to use for path computation
            src (obj): Compute a path from this node
            dest (obj): Compute a path to this node
            inp (obj): If `src` not a host set ingress to this value. Defaults to None.
            outp (obj): If `dest` not a host set the egress to this value. Defaults to None.
            path_key (tuple): Path key touple (source host to destination host)
            graph_sec (Graph): Topology object to use for computing the secondary path and
                path splices. `graph` is used for the primary path while `grap_sec`
                for any subsequent paths. Defaults to None, use `graph` for all paths.

        Returns:
            dict: Path information dictionary or an empty dictionary if can't compute
        """
        if path_key is None:
            path_key = (src, dest)

        gid = self._get_gid(path_key[0], path_key[1])
        path_primary, path_secondary, ports_primary, ports_secondary = ppc.find_path(
                        src, dest, graph, graph_sec, logger=self.logger)

        self.logger.info("PATH: %s to %s" % (src, dest))
        self.logger.info("PATH PRIMARY: %s" % path_primary)
        self.logger.info("PATH SECOND: %s" % path_secondary)

        # If the primary or secondary path is empty, return an empty dictionary
        if len(path_primary) == 0 or len(path_secondary) == 0:
            return {}

        # If the secondary graph is not defied used the primary to compute splices
        if graph_sec is None:
            graph_sec = graph

        # Find the required path splices for our two paths
        if self.LOOSE_SPLICE == False:
            splice = ppc.gen_splice(path_primary, path_secondary, graph_sec)
            splice.update(ppc.gen_splice(path_secondary, path_primary, graph_sec))
        else:
            splice = ppc.gen_splice_loose(path_primary, path_secondary, graph_sec)
            splice.update(ppc.gen_splice_loose(path_secondary, path_primary, graph_sec))

        self.logger.info("SPLICES: %s" % splice)

        # Compute the group table entries for the path
        group_table = {}
        for port in ports_primary:
            if port[0] not in group_table:
                group_table[port[0]] = []

            if port[2] not in group_table[port[0]]:
                group_table[port[0]].append(port[2])

        for port in ports_secondary:
            if port[0] not in group_table:
                group_table[port[0]] = []

            if port[2] not in group_table[port[0]]:
                group_table[port[0]].append(port[2])

        special_flows = {}
        for sw,sp in splice.iteritems():
            # Get the ports for the splice path and go through them
            ports = graph_sec.flows_for_path(sp)
            for port in ports:
                # Check if the current switch is at the start or end of the path splice
                if port[0] == sp[0] or port[0] == sp[len(sp)-1]:
                    if port[0] not in group_table:
                        group_table[port[0]] = []
                    if port[2] not in group_table[port[0]]:
                        group_table[port[0]].append(port[2])
                else:
                    # If its in the midle of the path we need to install a flow
                    # rule with in out port mappings.
                    # XXX: This occurs when a path splie has more than 2 switches
                    # and we are installing on a path other than the start and end
                    # of the splice.
                    if port[0] not in special_flows:
                        special_flows[port[0]] = []
                    if (port[1], port[2]) not in special_flows[port[0]]:
                        special_flows[port[0]].append((port[1], port[2]))

        # Work out the path attributes
        ingress = path_primary[1]
        egress = path_primary[len(path_primary)-2]
        in_port = ports_primary[0][1]
        out_port = ports_primary[len(ports_primary) - 1][2]

        if src not in self.hosts:
            ingress = inp
        if dest not in self.hosts:
            egress = outp

        # If this is a special pair of hosts on the same switch, we have no groups
        if ingress == egress and (ingress is not None or egress is not None):
            group_table = {}

        self.logger.info("GROUP_TABLE: %s" % group_table)
        self.logger.info("SPECIAL_FLOWS: %s" % special_flows)
        self.logger.info("VLAN/GID %s" % gid)
        self.logger.info("Ingress %s" % str(ingress))
        self.logger.info("Egress %s" % str(egress))
        self.logger.info("First Node IN_PORT %s" % in_port)
        self.logger.info("First Node OUT_PORT %s" % out_port)

        # Build an enriched path dictionary and return it
        new_path_details = {
            "ingress": ingress,
            "egress": egress,
            "groups": group_table,
            "special_flows": special_flows,
            "gid": gid,
            "in_port": in_port,
            "out_port": out_port,
            "path_primary": path_primary,
            "path_secondary": path_secondary,
            "path_splices": splice
        }

        return new_path_details


    def _compute_paths(self, graph, src, dest, dest_addr, dest_eth, inp=None, outp=None, path_key=None,
                        combine_gp={}, combine_special_flows={}):
        """ Compute and install paths between `src` and `dest`. Generate path info by
        calling ``compute_path_dict``. Method installs the computed path information by
        calling ``install_path_dict`` which works out the set of minimally required
        changes needed to transition existing rules on switches to the new paths.

        Args:
            graph (Graph): Topology graph object
            src (obj): Compute paths from this node
            dest (obj): Compute paths to this node
            dest_addr (str): IP address of destination (used by ingress rule)
            dest_eth (str): MAC address of destination (used by egress rule for translation)
            inp (obj): If `src` not a host set path info ingress to this value
            outp (obj): If `dest` not a host set path info egress to this value
            path_key (tuple): Src-dest key pair to use for path. Defaults to None which uses
                (src, dst) as key when saving path information.
            combine_gp (dict): Combine computed path group table with this dictionary. Defaults
                to {} (nothing to combine).
            combine_special_flows (dict): Combine computed path special flows table with these
                entries. Defaults to {} (nothing to combine).
        """
        if path_key is None:
            path_key = (src, dest)

        path_dict = self.compute_path_dict(graph, src, dest, inp=inp, outp=outp, path_key=path_key)

        # XXX: If the path dictionary is not empty, add the address and eth fields to the dict to
        # install
        if not len(path_dict) == 0:
            path_dict["address"] = dest_addr
            path_dict["eth"] = dest_eth

        self.install_path_dict(path_key, path_dict, combine_gp, combine_special_flows)


    def install_path_dict(self, path_key, path_dict, combine_gp={}, combine_special_flows={}):
        """ Install paths using a information dictionary `path_dict`. Method expects
        that `path_dict` is computed by ``compute_path_dict` and contains several
        default fielfds. The group and special flow dict entries of the path dict
        are combined with `combine_gp` and `combine_special_flows`, then paths are
        installed by calling ``_proc_path_diff` which works out the minimal changes
        to install  the new paths. Finally, if required, the ingress and egress rule
        are installed on the repsective switches and the path info is saved to
        `:cls:attr:(paths)` using the key `path_key`. Required fields are: path_primary
        (removed before install), path_secondary (removed), path_splice (removed), gid,
        in_port, out_port, ingress, egress, address, eth, groups and special_flows.

        Args:
            path_key (tuple): Src-dest key to use when installing path
            path_dict (dict): Path information dictionary to install
            combine_gp (dict): Combine groups of path dict with field before installing
                paths. Defaults to empty dict (do not combine anything).
            combine_special_flows (dict): Combine special flows of path dict with field
                before installing. Defaults to empty dict (do not combine anything).
        """
        # Split the path key into componenets
        src, dest = path_key

        # If new path is empty uninstall old paths.
        if len(path_dict) == 0:
            self.logger.info("Empty secondary or primary path, skipping path install")

            if path_key in self.paths:
                self._proc_path_diff(self.paths[path_key], {})
                self.logger.info("Removed old flow rules for path that no longer exists")
                del self.paths[path_key]

            self.logger.info("-----------------------------------")
            return

        # Extract the enriched path data, remove extra fields and save IP and ETH addr
        path_primary = path_dict["path_primary"]
        path_secondary = path_dict["path_secondary"]
        del path_dict["path_primary"]
        del path_dict["path_secondary"]
        del path_dict["path_splices"]
        gid = path_dict["gid"]
        fn_in_port = path_dict["in_port"]
        fn_out_port = path_dict["out_port"]
        ingress = path_dict["ingress"]
        egress = path_dict["egress"]
        dest_addr = path_dict["address"]
        dest_eth = path_dict["eth"]

        old_path_details = {}
        if path_key in self.paths:
            old_path_details = self.paths[path_key]

        self.__combine_table(path_dict["groups"], combine_gp)
        self.__combine_table(path_dict["special_flows"], combine_special_flows)
        self.logger.info("Dest IP: %s" % path_dict["address"])
        self.logger.info("Dest MAC: %s" % path_dict["eth"])
        self.logger.info("Installing GP: %s" % path_dict["groups"])
        self.logger.info("Installing Special Flows: %s" % path_dict["special_flows"])

        # Install the new path and check if we need to re-install ingress and egress
        install_ingress, install_egress = self._proc_path_diff(old_path_details, path_dict)

        # TODO: CHECK IF THE PORTS CHANGED, IF THEY DID CHECK IF WE NEED TO RE-INSTALL

        if src in self.hosts and dest in self.hosts and len(path_primary) == 3:
            # Just blindly install the ingress/egress special rule.
            # XXX: We can't really relay on dynamic checking if we need to change this as
            # the path dosen't save the in_port, so we can just simply install it blinbly.
            dp = get_switch(self, dpid=ingress)
            if len(dp) != 1 or dp[0] is None:
                self.logger.error("Can't find SW %s to install ingress rules" % sw)
            else:
                dp = dp[0].dp
                match = OFP_Helper.match(dp, in_port=fn_in_port, ipv4_dst=dest_addr)
                action = OFP_Helper.action(dp, eth_dst=dest_eth, out_port=fn_out_port)
                priority = 0

                self._add_flow(dp, match, action, priority=priority)
                self._install_arp_fix_rule(dp)

                path_dict["groups"] = {}
                self.paths[path_key] = path_dict

            self.logger.info("-----------------------------------")
            return

        if install_ingress and src in self.hosts:
            # Try and get the ingress switch and install the flows
            dp = get_switch(self, dpid=ingress)
            if len(dp) != 1 or dp[0] is None:
                    self.logger.error("Can't find SW %s(%s) to install ingress" %
                                        (ingress, gid))
            else:
                dp = dp[0].dp
                match, action, priority = self.__ingress_rule(dp, gid, fn_in_port, addr=dest_addr)
                self._add_flow(dp, match, action, priority=priority)
                self._install_arp_fix_rule(dp)
                self.logger.info("Installed ingress on sw %s" % ingress)

        if install_egress and dest in self.hosts:
            # Try and get the egress switch and install flow rules
            dp = get_switch(self, dpid=egress)
            if len(dp) != 1 or dp[0] is None:
                self.logger.error("Can't find SW %s(%s) to install egress" %
                                        (egress, gid))
            else:
                dp = dp[0].dp
                self._add_flow(dp,
                    OFP_Helper.match(dp, vlan=gid),
                    OFP_Helper.action(dp, vlan_pop=True, out_group=gid, eth_dst=dest_eth),
                        priority=1)

                self.logger.info("Installed egress on sw %s" % egress)

        # Save the path details and finish
        self.logger.info("-----------------------------------")
        self.paths[path_key] = path_dict

    def _proc_path_diff(self, old, new):
        """ Work out the set of minimal changed required to install the new paths. Return flags
        indicating if the ingress and egress rules need to be re-installed.

        TODO:
            FIXME: If a host moves to a new PORT/MAC, we have a problem as the egress will
        not be changed. This is an issue as our path dosen't store the destination MAC
        address so we can't check if the MAC of the port has changed, therfore packets will
        be discarded. For now, we are simply forcing re-installation of the egress.
        This needs to change and its a easy fix to resolve the MAC issue, just store the
        destination mac to the path.

        Args:
            old (dict): Details of old installed path we have to work out difference of.
            new (dict): Details of new path we are installing.

        Returns:
            (packed boolean): Install ingress rule, Install egress rule.
        """
        install_ingress = False
        install_egress = True
        remove_all = False

        # Optimisation check: if there is no old path just install everything
        if old == {}:
            # Go through and install groups
            for sw,gp in new["groups"].iteritems():
                self.logger.debug("Installing groups on new switch %s" % sw)
                dp = get_switch(self, sw)
                if len(dp) != 1 or dp[0] is None:
                    self.logger.error("Switch disconnected, can't install groups %s" % sw)
                    continue
                dp = dp[0].dp

                inst_flow = True
                if sw == new["ingress"] or sw == new["egress"]:
                    inst_flow = False
                self.__install_group(sw, new, dp, add_flow=inst_flow, modify=False)

            # Go through and install the special flow rules
            for sw,pts in new["special_flows"].iteritems():
                self.logger.debug("Installing special splice flow ruls on switch  %s" % sw)
                dp = get_switch(self, sw)
                if len(dp) != 1 or dp[0] is None:
                    self.logger.error("Switch disconnected, can't install groups %s" % sw)
                    continue
                dp = dp[0].dp

                for pt in pts:
                    self._add_flow(dp, OFP_Helper.match(dp, vlan=new["gid"], in_port=pt[0]),
                                    OFP_Helper.action(dp, out_port=pt[1]), priority=0)
                    self.logger.debug("Installed special flow rule %s on sw %s" % (pt, sw))
            return True, True

        # Remove all installed rules (no new paths or GID changed)
        if new == {} or not old["gid"] == new["gid"]:
            install_ingress = True
            install_egress = True
            remove_all = True

            # Remove ingress and egress if installed, not inter-domain or special rules
            if (old["ingress"] is not None and not isinstance(old["ingress"], tuple)):
                self.__delete_ingress_rule(old["gid"], old["address"], old["in_port"],
                        dpid=old["ingress"])

            if (old["egress"] is not None and not old["ingress"] == old["egress"] and
                        not isinstance(old["egress"], tuple)):
                self.__delete_egress_rule(old["gid"], dpid=old["egress"])
        else:
            # If ingress changed remove the old rule
            if (old["ingress"] is not None and not isinstance(old["ingress"], tuple) and
                        (not old["ingress"] == new["ingress"] or not old["in_port"] == new["in_port"] or
                            not old["address"] == new["address"])):
                self.__delete_ingress_rule(old["gid"], old["address"], old["in_port"],
                        dpid=old["ingress"])
                install_ingress = True

            # If egress changed remove the old rule
            # TODO: We need to check if the MAC has changed, if so modify/remove the old MAC
            if (old["egress"] is not None and not isinstance(old["egress"], tuple) and
                        not old["egress"] == new["egress"] and not old["ingress"] == old["egress"]):
                self.__delete_egress_rule(old["gid"], old["address"], old["in_port"],
                        dpid=old["ingress"])
                install_egress = True

        # Iterate through the old groups and remove rules that no longer exist
        gid = old["gid"]
        for sw,gp in old["groups"].iteritems():
            dp = get_switch(self, sw)
            if len(dp) != 1 or dp[0] is None:
                self.logger.info("Switch disconnected, can't delete rules %s" % sw)
                continue
            dp = dp[0].dp

            # If we need to remove everything or the switch dosen't exist in the new groups table
            # remove the groups and flow that redirects packets to the group.
            if remove_all or sw not in new["groups"] or new["groups"][sw] == []:
                self.logger.debug("SW %s no longer has rules, removing old rules" % sw)
                for port in gp:
                    if isinstance(port, tuple):
                        raise Exception("Found tuple in group table, tuples moved to special field!")
                        # XXX: This is just a invalid check as of now (remove for better performance)

                # Only remove the flow and group if it was previously installed
                if len(gp) > 0:
                    self._del_flow(dp, OFP_Helper.match(dp, vlan=gid), out_group=gid)
                    self._del_group(dp, gid)
                continue

            # If the old group table is different to the new group table just re-install it
            # This check assmes previous conditions are both false (i.e. not re-ionstall and sw exists)
            gp_diff, is_mod = self._group_different(gp, new["groups"][sw])
            if gp_diff:
                self.logger.debug("Group changed on sw %s, reinstalling!" % sw)
                inst_flow = True
                if sw == new["ingress"] or sw == new["egress"]:
                    inst_flow = False
                self.__install_group(sw, new, dp, add_flow=inst_flow, modify=is_mod)

        # Iterate through the old special flows and remove rules that should no longer exist
        for sw,pts in old["special_flows"].iteritems():
            dp = get_switch(self, sw)
            if len(dp) != 1 or dp[0] is None:
                self.logger.info("Switch disconnected, can't delete rules %s" % sw)
                continue
            dp = dp[0].dp

            # If we need to remove everything or the switch dosen't have special flow rules anymore
            # remove the old rules
            if remove_all or sw not in new["special_flows"] or new["special_flows"][sw] == []:
                self.logger.debug("SW %s no longer has special flow rules, removing rules" % sw)
                for pt in pts:
                    self.logger.debug("Removing special flow rule %s from %s" % (pt, sw))
                    self._del_flow(dp, OFP_Helper.match(dp, vlan=gid, in_port=pt[0]), out_port=pt[1])
                continue

            # Go through the special flow rules and remove the ones that are no longer in sw
            for pt in pts:
                if pt not in new["special_flows"][sw]:
                    self.logger.debug("Removing special flow rule %s from %s" % (pt, sw))
                    self._del_flow(dp, OFP_Helper.match(dp, vlan=gid, in_port=pt[0]), out_port=pt[1])

        # Iterate through new groups and install groups for new switches (or re-install if remove_all
        # so GID changed)
        if "groups" in new:
            for sw,gp in new["groups"].iteritems():
                if remove_all or sw not in old["groups"]:
                    self.logger.debug("Installing groups on new switch %s" % sw)

                    dp = get_switch(self, sw)
                    if len(dp) != 1 or dp[0] is None:
                        self.logger.error("Switch disconnected, can't install groups %s" % sw)
                        continue
                    dp = dp[0].dp

                    inst_flow = True
                    if sw == new["ingress"] or sw == new["egress"]:
                        instal_flow = False
                    self.__install_group(sw, new, dp, add_flow=inst_flow, modify=False)

        # Iterate through the new special flows and install rules that have changed (or re-install everything
        # if remove_all so GID change).
        if "special_flows" in new:
            for sw,pts in new["special_flows"].iteritems():
                for pt in pts:
                    dp = get_switch(self, sw)
                    if len(dp) != 1 or dp[0] is None:
                        self.logger.error("Switch disconnected, can't install special flows %s" % sw)
                        continue
                    dp = dp[0].dp

                    if remove_all or sw not in old["special_flows"] or pt not in old["special_flows"][sw]:
                        self._add_flow(dp, OFP_Helper.match(dp, vlan=new["gid"], in_port=pt[0]),
                                        OFP_Helper.action(dp, out_port=pt[1]), priority=0)
                        self.logger.debug("Installed flow tuple rule %s on sw %s" % (pt, sw))

        # Return if we need to install the ingress and egress rules
        return install_ingress, install_egress


    def __combine_table(self, target, combine):
        """ Combine a group table or sepcial flow table into a single element. Copies `combine` to `target`.

        Args:
            target (dict): Target dictionary to copy results to
            combine (dict): Dictionary with elements to copy
        """
        for sw, ports in combine.iteritems():
            if sw not in target:
                target[sw] = []

            for port in ports:
                if port not in target[sw]:
                    target[sw].append(port)


    def __install_group(self, sw, data, dp, add_flow=True, modify=True):
        """ Install a group table for a specific switch. If `add_flow` is true a flow
        rule to redirect packets to the created group is installed as well. If
        `modify` we will perform a group modification. `data` has to contain a 'gid'
        and 'groups' filed. 'groups' should have a entry for the specified `sw`.

        Args:
            sw (str): Switch that we want to install groups for
            data (dict): Path details for group we are installing. See ``_compute_paths``.
            dp (controller.datapath): Datapath of switch.
            add_flow (bool): Add flow rule to redirect to group? Defaults to True (yes).
            modify (bool): Should we modify the groups? Defaults to True (modify).
        """
        gid = data["gid"]
        data = data["groups"][sw]
        bucket = []
        for port in data:
            if isinstance(port, tuple):
                raise Exception("Found tuple in group table, tuples moved to special field!")
                # XXX: Special flow rule tuples moved to seperate field
                # Install a group tuple flow port rule
                #self._add_flow(dp, OFP_Helper.match(dp, vlan=gid, in_port=port[0]),
                #            OFP_Helper.action(dp, out_port=port[1]), priority=0)
                #self.logger.debug("Installed flow tuple rule %s on sw %s" % (port, sw))
            else:
                # Add the port to the bucket list
                bucket.append((port, OFP_Helper.action(dp, out_port=port)))

        # Add or change the group entry.
        # XXX: If the bucket is empty this means that we have no group entries so
        # do not install an empty group table
        if len(bucket) > 0:
            self._add_group(dp, gid, bucket, modify=modify)

            if add_flow:
                self._add_flow(dp, OFP_Helper.match(dp, vlan=gid),
                        OFP_Helper.action(dp, out_group=gid), priority=0)
            self.logger.debug("Installed group on sw %s" % sw)


    def __delete_ingress_rule(self, gid, addr, in_port, dpid=None, dp=None):
        """ Remove a installed ingress rule from a switch with dpid `dpid` or
        dp `dp`. If `dp` is not specified, `dpid` is used to retrieve the switch dp.
        Either `dp` or `dpid ` has to be specified to remove the ingress rule.

        Args:
            gid (int): Group and VLAN id of the ingress rule (path that installed it)
            addr (str): Match address of ingress rule
            in_port (int): Input port of ingress rule match
            dpid (obj): DPID of the switch. Defaults to None
            dp (controller.datapath): Datapath of switch. Defaults to None.
        """
        if dpid is None and dp is None:
            # Incorrect arguments used for method, write error and return
            self.logger.error("Need either a DPID or a DP instance to remove ingress rule")
            return

        # Retrieve the DP instance from the ID if not provided
        if dp is None:
            dp = get_switch(self, dpid)
            if len(dp) != 1 or dp[0] is None:
                self.logger.info("Ingress disconnected, can't delete rule")
                return
            dp = dp[0].dp

        # Remove the ingress rule
        ingress_match, ingress_action, ingress_priority = self.__ingress_rule(dp,
            gid, in_port, addr)
        self._del_flow(dp, ingress_match)
        self.logger.debug("Delete ingress rule for sw with dpid %s" % dp.id)


    def __delete_egress_rule(self, gid, dpid=None, dp=None):
        """ Remove a installed egress rule from a switch with dpid `dpid` or
        dp `dp`. If `dp` is not specified, `dpid` is used to retrieve the switch dp.
        Either `dp` or `dpid ` has to be specified to remove the egress rule.

        Args:
            gid (int): Group and VLAN id of the egress rule
            dpid (obj): DPID of the switch. Defaults to None
            dp (controller.datapath): Datapath of switch. Defaults to None.
        """
        if dpid is None and dp is None:
            # Incorrect arguments used for method, write error and return
            self.logger.error("Need either a DPID or a DP instance to remove ingress rule")
            return

        # Retrieve the DP instance from the ID if not provided
        if dp is None:
            dp = get_switch(self, dpid)
            if len(dp) != 1 or dp[0] is None:
                self.logger.info("Egress disconnected, can't delete rule")
                return
            dp = dp[0].dp

        self._del_flow(dp, OFP_Helper.match(dp, vlan=gid), out_group=gid)
        self.logger.debug("Delete egress rule for sw with dpid %s" % dp.id)


    def __ingress_rule(self, dp, gid, in_port, addr=None):
        """ Generate the match, action and priority to be used for the ingress switch
        rule that takes packets from hosts, VLAN tags them and sends them through the
        network to the destinatio.

        Args:
            dp (controller.datapath): Datapath of the switch
            gid (int): Group ID or VLAN VID to apply to packet
            addr (str): Address of the destination. Defaults to None (ignore)
        """
        return (OFP_Helper.match(dp, in_port=in_port, ipv4_dst=addr), OFP_Helper.action(dp,
                    vlan=gid, out_group=gid), 0)


    def invert_group_ports(self, hkey, node, groupID):
        """ Modify the ports of a group table where the primary port will be appended to the end
        and a new port made primary.

        Args:
            hkey (tuple): Host pair whos groups we are changing.
            node (tuple): Switch, port of new primary port of path
            groupID (int): ID of group we want to invert.
        """
        # If no node was provied (dummy trigger inver operation) just return
        if node is None:
            return

        # Check if the switch is connected
        sw,new_pt = node
        dp = get_switch(self, dpid=sw)
        if len(dp) != 1 or dp[0] is None:
            self.logger.error("Can't find SW %s to install groups" % sw)
            return
        dp = dp[0].dp

        # Remove the current primary port and make sure the new port exists in the group table
        old_pt = self.paths[hkey]["groups"][sw][0]
        gp = self.paths[hkey]["groups"][sw][1:]
        if new_pt not in gp:
            raise Exception("Can't invert group for path %s as new port %s not in group entry %s" %
                (hkey, node, gp))

        # Remove the new port and re-build the group entry
        gp.remove(new_pt)
        gp.insert(0, new_pt)
        gp.append(old_pt)
        self.paths[hkey]["groups"][sw] = gp

        # Send the group update the switch if valid
        bucket = []
        for p in gp:
            bucket.append((p, OFP_Helper.action(dp, out_port=p)))
        if len(bucket) > 0:
            self._add_group(dp, groupID, bucket, modify=True)
            self.logger.info("Inverted GP of %s at %s from %s to %s (GP: %s)" % (hkey, sw, old_pt, new_pt, gp))


    def _process_flow_stats(self, dp, body):
        """ Iterate through the OpenFlow stats reply message body and extract the stats
        we are intrested in. This method will generate a list of ingress switches from
        `:cls:attr:(paths)` and iterate through the flow stats to find the ingress
        flow rules (i.e. counts per path).

        Args:
            dp (controller.datapath): Datapath of switch to install rule to
            body (List of OFPFlowStats): List of stats reply data
        """

        # If a state rebuild is in progress, process the flow state from the stats
        if self._rebuild_state_in_progress():
            self._process_flow_desc(dp, body)

        # Generate the list of ingress switches from the topology dictionary
        # XXX: Re-evaluate this, this may fail
        ingress_sw = [val["ingress"] for key,val in self.paths.iteritems()]

        # Generate a list of inter-domain ingress links (only add resolved domains)
        inter_dom_ingress_sw = []
        for ul in self.unknown_links.iteritems():
            if not isinstance(ul[1], list) and ul[0][0] not in inter_dom_ingress_sw:
                inter_dom_ingress_sw.append(ul[0][0])

        # Check if the reply is from an ingress switch
        if dp.id in ingress_sw or dp.id in inter_dom_ingress_sw:
            for key,val in self.paths.iteritems():
                # XXX: Only collect stats for ingress rules and reconstution of inter-domain
                # path stats. Do not collect stats for special rules where src and dest are
                # on the same switch.
                if ((isinstance(val["ingress"], tuple) and not val["ingress"][0] == dp.id) or
                        (not isinstance(val["ingress"], tuple) and val["ingress"] == val["egress"])):
                    continue

                ing_match = None
                ing_action = None
                ing_inst = None

                # Generate the rules to extract the correct counts for the host pair
                if isinstance(val["ingress"], tuple):
                    # Create the expected GID redirect rule for the host pair
                    ing_match = OFP_Helper.match(dp, vlan=val["gid"])
                    ing_action = OFP_Helper.action(dp, out_group=val["gid"])
                    ing_inst = OFP_Helper.apply(dp, ing_action)
                elif val["ingress"] == dp.id:
                    # Create the expected ingress rule for the pair
                    ing_match, ing_action, ing_priority = self.__ingress_rule(dp, val["gid"],
                                                               val["in_port"], val["address"])
                    ing_inst = OFP_Helper.apply(dp, ing_action)
                else:
                    # This switch dosen't match the host pair, skip it
                    continue

                # Iterate through the flows retrieved and find rule stats
                for index in range(len(body)):
                    flow = body[index]
                    if (OFP_Helper.match_obj_eq(flow.match, ing_match) and
                            OFP_Helper.instruction_eq(flow.instructions, ing_inst)):
                        self.logger.debug("PATH stats for %s (PKT: %s, BYTE: %s)" %
                                            (key, flow.packet_count, flow.byte_count))

                        # Initiate the stats dict if it dosen't exist
                        if "stats" not in self.paths[key]:
                            self.paths[key]["stats"] = {
                                "pkts": 0,
                                "bytes": 0,
                                "total_pkts": 0,
                                "total_bytes": 0,
                                "pkts_persec": 0,
                                "bytes_persec": 0,
                                "total_pkts_persec": 0,
                                "total_bytes_persec": 0,
                                "total_time": 0
                            }

                        # Compute and save the stats
                        stats = self.paths[key]["stats"]
                        stats["pkts"] = flow.packet_count - stats["total_pkts"]
                        stats["bytes"] = flow.byte_count - stats["total_bytes"]
                        stats["total_time"] = flow.duration_sec
                        stats["total_pkts"] = flow.packet_count
                        stats["total_bytes"] = flow.byte_count

                        # Check if the time is non-zero if is can't compute per second
                        if flow.duration_sec > 0:
                            stats["pkts_persec"] = round(float(stats["pkts"]) /
                                        float(self.get_poll_rate()), 2)
                            stats["bytes_persec"] = round(float(stats["bytes"]) /
                                        float(self.get_poll_rate()), 2)
                            stats["total_pkts_persec"] = round(float(flow.packet_count) /
                                        float(flow.duration_sec), 2)
                            stats["total_bytes_persec"] = round(float(flow.byte_count) /
                                        float(flow.duration_sec), 2)

                        # Once we have found the stats delete it and exit the processing
                        del body[index]
                        break


    def _group_different(self, old_gp, new_gp):
        """ Check if two groups are different. Method takes into account ordering of ports

        Args:
            old_gp (list): List of ports to compare against
            new_gp (list): List of ports to compare with

        Returns:
            bool, bool: First element is false if the groups are the same and true if they differ.
                Second element is true if a mod operation needs to be performed, false if no previous
                rules installed.
        """
        different = (old_gp != new_gp)
        is_mod = (len(old_gp) > 0)
        return different, is_mod


    def _ingress_change(self, vid, sw, pn):
        """ An ingress change for a inter-domain path was detected. Find the installed path,
        modify it's details and notify the root controller.

        Args:
            vid (int): GID or VLAN id of the host key
            sw (int): DPID of the switch where the ingress change was detected
            pn (int): Ingress port where the change packet was received/

        """
        # Get the host pair from the GID
        hkey = self._get_reverse_gid(vid)
        if hkey is None:
            self.logger.error("Could not find host pair for ingress change detection VID %d" % vid)
            return

        # Ingress change wait is in progress, do not swap path
        if self._is_ing_change_wait(hkey):
            return

        # Find the effective path
        path_info = self.paths[hkey]
        path = ppc.group_table_to_path(path_info, self.graph, (sw, pn))
        new_egress_sw = path[len(path)-1]
        new_egress_pn = new_egress_sw[2]
        new_egress_sw = new_egress_sw[0]

        gid = path_info["gid"]
        old_ingress = path_info["ingress"]
        new_ingress = (sw, pn)
        old_egress = path_info["egress"]
        new_egress = (new_egress_sw, new_egress_pn)

        if old_ingress == new_ingress:
            # No change occured so just stop
            return

        # Update the ingress details and egress (if we are not a destination segmnet)
        path_info["ingress"] = new_ingress
        self.logger.info("Modified ingress of %s from %s to %s" % (hkey, old_ingress, new_ingress))
        if isinstance(old_egress, tuple):
            path_info["egress"] = new_egress
            self.logger.info("Modified egress of %s from %s to %s" % (hkey, old_egress, new_egress))

        # Remove the old ingress change detection rule and re-install it on the old ingress
        self.__delete_ingress_change_detect_rule(pn, gid, dpid=sw)
        path_info["ingress_change_detect"].remove(new_ingress)
        path_info["ingress_change_detect"].append(old_ingress)
        self.__install_ingress_change_detect_rule(old_ingress[1], hkey, dpid=old_ingress[0])

        # Notify the root controller of the ingress change
        self.ctrl_com.notify_ingress_change(hkey, old_ingress, new_ingress, old_egress, new_egress)


    def __install_ingress_change_detect_rule(self, in_port, hkey, dpid=None, dp=None):
        """ Install a rule to help detect when an inter-domain path's ingress changes. The rule
        matches packets on port `in_port` of switch `dpid` or `dp` that have a specific VLAN VID.
        Packets that match the first rule are redirect to the output group and to table 1 where
        a seperate rule send the packets to the controller (with a meter applied to limit them to
        1 packet/s). The priority of the egress rules is set to 2. Either `dp` or `dpid` has to be
        specified.

        Args:
            in_port (int): Input port that we should capture packets and send them
                to the controller
            hkey (str, str): Pair to install ingress change detection for
            dpid (obj): DPID of the switch. Defaults to None
            dp (controller.datapath): Datapath of switch. Defaults to None.
        """
        if dpid is None and dp is None:
            # Incorrect arguments used for method, write error and return
            self.logger.error("Need either a DPID or a DP instance to install ingress change rule")
            return

        # Retrieve the DP instance from the ID if not provided
        if dp is None:
            dp = get_switch(self, dpid)
            if len(dp) != 1 or dp[0] is None:
                self.logger.info("Can't find switch")
                return
            dp = dp[0].dp
            dpid = dp.id

        # On modification of ingress change detection add wait before detecting ingress change
        # to deal with inflight packets.
        self._init_ing_change_wait(hkey)

        pinfo = self.paths[hkey]
        gid = pinfo["gid"]
        # Install the required rules and meter
        match = OFP_Helper.match(dp, in_port=in_port, vlan=gid)
        action = None
        if dpid == pinfo["egress"]:
            action = OFP_Helper.action(dp, vlan_pop=True, out_group=gid, eth_dst=pinfo["eth"])
            action.extend(OFP_Helper.action(dp, vlan=gid))
        else:
            action = OFP_Helper.action(dp, out_group=gid)
        self._add_flow(dp, match, action, priority=2, extra_inst=[OFP_Helper.goto_table(dp, 1)])

        self._add_meter(dp, gid, 1)

        match = OFP_Helper.match(dp, vlan=gid)
        action = OFP_Helper.action(dp, out_ctrl=1)
        self._add_flow(dp, match, action, table_id=1, extra_inst=[OFP_Helper.apply_meter(dp, gid)])
        self.logger.info("Added ingress change rule for sw %s port %s" % (dp.id, in_port))


    def __delete_ingress_change_detect_rule(self, in_port, gid, dpid=None, dp=None):
        """ Remove an install ingress change detection rule. Either `dp` or `dpid` has to be
        specified to remove the egress rule.

        Args:
            in_port (int): Input port that we should capture packets and send them
                to the controller
            gid (int): Group and VLAN id of traffic this ingress should be associated with
            dpid (obj): DPID of the switch. Defaults to None
            dp (controller.datapath): Datapath of switch. Defaults to None.
        """
        if dpid is None and dp is None:
            # Incorrect arguments used for method, write error and return
            self.logger.error("Need either a DPID or a DP instance to remove ingress change rule")
            return

        # Retrieve the DP instance from the ID if not provided
        if dp is None:
            dp = get_switch(self, dpid)
            if len(dp) != 1 or dp[0] is None:
                self.logger.info("Can't find switch")
                return
            dp = dp[0].dp

        match = OFP_Helper.match(dp, vlan=gid)
        self._del_flow(dp, match, tableID=1)
        self._del_meter(dp, gid)
        match = OFP_Helper.match(dp, in_port=in_port, vlan=gid)
        self._del_flow(dp, match, tableID=0, out_group=gid)
        self.logger.info("Delete ingress change rule for sw %s port %s" % (dp.id, in_port))


    def _process_flow_desc(self, dp, body):
        """ Extract flow states during a state recovery interval from the flow statistics """
        # Extract rules from the flow stats
        # XXX: OF 1.5 introduces OFPFlowDescStatsRequest (similar to group)
        for flow in body:
            if flow.table_id != 0:
                continue

            ofpp = dp.ofproto_parser
            match = flow.match
            insts = flow.instructions
            if match.get("vlan_vid") is not None:
                for inst in insts:
                    # If this is an egress rule process it's fields and restore the state
                    if (isinstance(inst, ofpp.OFPInstructionActions) and
                        isinstance(inst.actions[0], ofpp.OFPActionPopVlan) and
                        isinstance(inst.actions[1], ofpp.OFPActionSetField) and
                        isinstance(inst.actions[2], ofpp.OFPActionGroup)):

                        gid = inst.actions[2].group_id
                        hosts = self._get_reverse_gid(gid)
                        if hosts == None:
                            self.logger.error("Could not find host pair for GID %d" % gid)
                            continue

                        if hosts in self.paths:
                            self.paths[hosts]["egress"] = dp.id
                            if dp.id in self.paths[hosts]["groups"]:
                                self.paths[hosts]["out_port"] = self.paths[hosts]["groups"][dp.id][0]
                        else:
                            self.paths[hosts] = {
                                "ingress": None,
                                "egress": dp.id,
                                "groups": {},
                                "special_flows": {},
                                "gid": gid,
                                "in_port": None,
                                "out_port": None,
                            }

                        # We found the egress match so stop processing rule instructions
                        break

            elif match.get("in_port") is not None and match.get("ipv4_dst") is not None:
                for inst in insts:
                    # If this is a ingress rule prucess it's fields and restore the state
                    if (isinstance(inst, ofpp.OFPInstructionActions) and
                        isinstance(inst.actions[0], ofpp.OFPActionPushVlan) and
                        isinstance(inst.actions[1], ofpp.OFPActionSetField) and
                        isinstance(inst.actions[2], ofpp.OFPActionGroup)):

                        gid = inst.actions[2].group_id
                        hosts = self._get_reverse_gid(gid)
                        if hosts == None:
                            self.logger.error("Could not find host pair for GID %d" % gid)
                            continue

                        if hosts in self.paths:
                            self.paths[hosts]["ingress"] = dp.id
                            self.paths[hosts]["in_port"] = match.get("in_port")
                            self.paths[hosts]["address"] = match.get("ipv4_dst")
                        else:
                            self.paths[hosts] = {
                                "ingress": dp.id,
                                "egress": None,
                                "groups": {},
                                "special_flows": {},
                                "gid": gid,
                                "in_port": match.get("in_port"),
                                "out_port": None,
                                "address": match.get("ipv4_dst")
                            }

                        # We found the ingress match so stop processing rule instructions
                        break

        self.logger.info("Rebuild SW flow state of DPID %s" % dp.id)
        self._proc_sw_state(dp.id, "flow")


    def _process_group_desc(self, dp, body):
        """ Process a group description reply messages to update the current state dictionary """
        for group in body:
            if group.type == dp.ofproto.OFPGT_FF:
                # If no host pair was found log error and skip entry
                hosts = self._get_reverse_gid(group.group_id)
                if hosts == None:
                    self.logger.error("Could not find host pair for GID %d" % group.group_id)
                    continue

                ports = []
                for bucket in group.buckets:
                    if len(bucket.actions) != 1 or bucket.actions[0].port != bucket.watch_port:
                        self.logger.error("Incorrect group entry for GID %d, skipping" % group.group_id)
                        continue
                    ports.append(bucket.watch_port)

                self.logger.info("DPID: %d GID: %d %s | PORTS: %s" % (dp.id, group.group_id, hosts, ports))

                if hosts not in self.paths:
                    self.paths[hosts] = {
                        "ingress": None,
                        "egress": None,
                        "groups": {dp.id: ports},
                        "special_flows": {},
                        "gid": group.group_id,
                        "in_port": None,
                        "out_port": None,
                    }
                elif dp.id != self.paths[hosts]["groups"] or self.paths[hosts]["groups"][dp.id] != ports:
                    self.paths[hosts]["groups"][dp.id] = ports

                    # Check if we can update the egress port
                    egress = self.paths[hosts]["egress"]
                    if egress is not None and egress == dp.id:
                        self.paths[hosts]["out_port"] = ports[0]


        self.logger.info("Rebuild SW group state of DPID %s" % dp.id)
        self._proc_sw_state(dp.id, "gp")
