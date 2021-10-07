#!/usr/bin/python

from ryu.topology.api import get_switch
import OFP_Helper
from TopoDiscoveryController import TopoDiscoveryController


class ReactiveController(TopoDiscoveryController):
    """ Reactive controller that implements restoration recovery. When failures occur
    controller will modify the topo `:cls:attr:(graph)` and recompute the paths.

    Attributes:
        paths (dict): List of installed paths onto the switches. Has the format:
            {(src, dst) : {
                "ingress": Switch ID, "egress": Switch ID, "gid": Path VLAN ID,
                "address":  Destination address, "flows": [(sw_id, in_port, out_port)]
            }}
    """
    CONTROLLER_NAME = "REACTIVE"


    def __init__(self, *args, **kwargs):
        """ Initiate the controller """
        super(ReactiveController, self).__init__(*args, **kwargs)
        self.paths = {}

        # XXX: Disable TE optimisation for the reactive controller, not supported
        self.TE.in_progress = True


    # -------------------------- HELPER METHODS --------------------------


    def topo_changed(self):
        """ Install forwarding rules between all host pairs in `:cls:attr:(hosts)` """
        for host_1 in self.hosts:
            for host_2 in self.hosts:
                # Don't compute a path to ourselves
                if host_1 == host_2:
                    continue

                self.__install_shortest_path(host_1, host_2)


    def __install_shortest_path(self, src, dst):
        """ Install a path onto the switches between host `src` and `dst`. If no suitable
        path exists any old path that is already installed will be uninstalled.

        Args:
            src (str): Source of the new path
            dst (str): Destination of the new path
        """
        self.logger.info("Install path from %s to %s" % (src, dst))
        tup = (src,dst)
        path = self.graph.shortest_path(src, dst)
        if path == []:
            # If old path installed remove it (path no longer exists)
            if tup in self.paths:
                self.logger.info("\tRemoving old path %s" % self.paths[tup]["flows"])
                vid = self.paths[tup]["vid"]
                ing = self.paths[tup]["ingress"]
                addr = self.paths[tup]["address"]
                for p in self.paths[tup]["flows"]:
                    dpid = p[0]
                    in_port = p[1]
                    out_port = p[2]

                    self.logger.info("\tDel link %s (in: %s | out: %s)" %
                                        (dpid, in_port, out_port))

                    dp = get_switch(self, dpid=dpid)
                    if dp is None or len(dp) == 0:
                        self.logger.info("\tSwitch not connected, skipping delete")
                        continue
                    dp = dp[0].dp

                    # Delete the path flow
                    if dpid == ing:
                        self._del_flow(dp,
                            OFP_Helper.match(dp, in_port=in_port, vlan=vid, ipv4_dst=addr))
                    else:
                        self._del_flow(dp, OFP_Helper.match(dp, in_port=in_port, vlan=vid))

                del self.paths[tup]
            return

        # Get the path flows/ports and compute the VID
        vid = self._get_gid(src, dst)
        path_flows = self.graph.flows_for_path(path)

        self.logger.info("\tPath: %s Ports: %s" % (path, path_flows))
        ing = path_flows[0][0]
        egr = path_flows[len(path_flows)-1][0]
        addr = self.graph.get_port_info(dst, -1)
        eth_dst = addr["eth_address"]
        addr = addr["address"]
        self.logger.info("\ting: %s, egr: %s, vid: %s, addr: %s, eth_dst: %s" %
            (ing, egr, vid, addr, eth_dst))

        # Iterate through the ports of the path
        old_path = self.paths[tup]["flows"] if tup in self.paths else []
        old_vid = self.paths[tup]["vid"] if tup in self.paths else None
        old_addr = self.paths[tup]["address"] if tup in self.paths else None
        for p in path_flows:
            install = True
            for i in range(len(old_path)):
                pOld = old_path[i]
                if pOld == p and old_vid == vid and old_addr == addr:
                    self.logger.info("\tOld path port same %s, not re-isntalling" % str(pOld))
                    # New path same as old, don't re-install
                    install = False
                    del old_path[i]
                    break

                if pOld[1] == p[1] and old_vid == vid and old_addr == addr:
                    # Match of old is same (an add should just change action)
                    self.logger.info("\tOld path in same %s, not removing" % str(pOld))
                    del old_path[i]
                    break

            if install == False:
                continue

            dpid = p[0]
            in_port = p[1]
            out_port = p[2]
            self.logger.info("\tAdd SW %s in port: %s, out port: %s, vid: %s, addr: %s" %
                    (dpid, in_port, out_port, vid, addr))

            # Retrieve the datapath of the switch and make sure its connected
            dp = get_switch(self, dpid=dpid)
            if dp is None or len(dp) == 0:
                self.logger.error("\tSwitch not connected, skipping add!")
                continue
            dp = dp[0].dp

            if dpid == ing:
                # Install the ingress rule
                ingress_match, ingress_action, ingress_priority = self.__ingress_rule(dp,
                    in_port, out_port, vid, addr=addr)
                self._add_flow(dp, ingress_match, ingress_action, priority=ingress_priority)

                # XXX: Install the ARP fix rule
                self._install_arp_fix_rule(dp)
                self.logger.info("\tInstalled ingress rule on %s" % dpid)
            elif dpid == egr:
                # Install the egress rule
                self._add_flow(dp, OFP_Helper.match(dp, in_port=in_port, vlan=vid),
                    OFP_Helper.action(dp, vlan_pop=True, out_port=out_port, eth_dst=eth_dst))
                self.logger.info("\tInstalled egress rule on %s" % dpid)
            else:
                # Install a standard rule
                self._add_flow(dp, OFP_Helper.match(dp, in_port=in_port, vlan=vid),
                    OFP_Helper.action(dp, out_port=out_port))
                self.logger.info("\tInstalled rule on %s" % dpid)

        # Remove old flows that are no longer present in new path
        self.logger.info("\tRemoving old installed flows that are no longer used")
        for p in old_path:
            dpid = p[0]
            in_port = p[1]
            out_port = p[2]
            self.logger.info("\tDel SW %s in port: %s, out port: %s, vid: %s, addr: %s" %
                (dpid, in_port, out_port, old_vid, old_addr))

            # Retrieve the datapath of the switch and make sure its connected
            dp = get_switch(self, dpid=dpid)
            if dp is None or len(dp) == 0:
                self.logger.error("Switch not connected, skipping over!")
                continue
            dp = dp[0].dp

            # Delete the path flow
            if dpid == ing:
                self._del_flow(dp,
                    OFP_Helper.match(dp, in_port=in_port, vlan=old_vid, ipv4_dst=old_addr))
                self.logger.info("\tDeleted ingress rule on %s" % dpid)
            else:
                self._del_flow(dp, OFP_Helper.match(dp, in_port=in_port, vlan=old_vid))
                self.logger.info("\tDeleted rule on %s" % dpid)

        # Add the path info to the installed path dictionary
        self.paths[tup] = {"ingress": ing, "egress": egr, "flows": path_flows, "vid": vid,
                            "address": addr}


    def __ingress_rule(self, dp, in_port, out_port, vid, addr=None):
        """ Generate the match, action and priority to be used for ingress switches.
        The rule will match all packets from a `in_port` with dest address `addr`. The
        packets are VLAN tagged with ID `vid` and outputed on `out_port`.

        Args:
            dp (controller.datapath): Datapath of the switch
            in_port (int): Input port to match packets on
            out_port (int): Port to output patckets that match to
            vid (int): VLAN ID to push to packets that match
            addr (str): Address of the destination. Defaults to None (ignore)

        Returns:
            (OFPMatch, List of OFPAction, int): Match, action and priority of ingress rule
        """
        return (OFP_Helper.match(dp, in_port=in_port, ipv4_dst=addr),
                    OFP_Helper.action(dp, vlan=vid, out_port=out_port), 0)


    def _process_flow_stats(self, dp, body):
        """ Iterate through the OpenFlow stats reply message body and extract the stats
        we are intrested in. Generate a list of ingress switches from `:cls:attr:(paths)`
        and iterate through the flow stats reply to find the ingress flow rules (i.e.
        counts per path).

        Args:
            dp (controller.datapath): Datapath of switch to install rule to
            body (List of OFPFlowStats): List of stats reply data
        """
        # Generate the list of ingress switches from the topology dictionary
        ingress_sw = [val["ingress"] for key,val in self.paths.iteritems()]

        # Check if the replky is from an ingress switch
        if dp.id in ingress_sw:
            for key,val in self.paths.iteritems():
                if val["ingress"] == dp.id:
                    in_port = val["flows"][0][1]
                    out_port = val["flows"][0][2]
                    ing_match, ing_action, ing_priority = self.__ingress_rule(dp, in_port,
                                                out_port, val["vid"], addr=val["address"])
                    ing_inst = OFP_Helper.apply(dp, ing_action)

                    # Iterate through the flows retrieved and find ingress rule stats
                    for index in range(len(body)):
                        flow = body[index]
                        if (OFP_Helper.match_obj_eq(flow.match, ing_match) and
                                OFP_Helper.instruction_eq(flow.instructions, ing_inst)):
                            self.logger.debug("PATH stats for %s (PKT: %s, BYTE: %s)" %
                                                (key, flow.packet_count, flow.byte_count))

                            # Initiate the stats dict if it dosen't exist
                            if "stats" not in self.paths[key]:
                                self.paths[key]["stats"] = {
                                    "pkts": 0, "bytes": 0, "total_pkts": 0,
                                    "total_bytes": 0, "pkts_persec": 0,
                                    "bytes_persec": 0, "total_pkts_persec": 0,
                                    "total_bytes_persec": 0, "total_time": 0}

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


    def _ingress_change(self, vid, sw, pn):
        """ On ingress change detection don't do anything, OP not supported """
        self.logger.info("Ing change received VID %d (SW %s, PN %d). OP Ignored!" % (vid, sw, pn))
        pass


    def _process_flow_desc(self, dp, body):
        """ On flow description received don't do anything, OP not supported """
        self.logger.info("Flow desc received for dpid %d. OP Ignored!" % (dp.id))
        pass


    def _process_group_desc(self, dp, body):
        """ On group description received don't do anything, OP not supported """
        self.logger.info("Group desc received for dpid %d. OP Ignored!" % (dp.id))
        pass
