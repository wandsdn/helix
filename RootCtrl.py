#!/usr/bin/python

import pika
import pickle
from threading import Timer, Lock
import pprint
import logging
import logging.handlers
from argparse import ArgumentParser
import traceback
import time

from ShortestPath.dijkstra_te import Graph
from TE import CSPFPrune, update_link_traffic
from TE import find_solset_min_spare_capacity


class RootCtrl(object):
    """ Root controller object which communicates with local controllers and computes /
    manages inter-domain routing. This module uses RabbitMQ as the communication channel.

    Attributes:
        te_candidate_sort_rev (bool): Sort source-destination pairs in
            descending order (True) or ascending (False).
        te_partial_accept (bool): Accept partial TE solutions (true) which are
            over the threshold but cause no congestion loss.
        _ctrls (dict): List of local controllers and attributes (timeout timers)
            format: {<cid>: {"timer": <timer>, "count": <count>}, ...}
        _topo (dict): Dictionary that contains inter-domain topology
            format: {<cid>: {"hosts": [...], "switches": [...], "neighbours": [<n>, ...]}, ...}
            format of <n>: {(<n_cid>, <sw>, <port>): {"switch": <n_sw>, "port": <n_port>}
        _graph (Graph): Graph object of the current network
        _old_paths (dict): Dictionary of the old computed path (path information)
            format: {(<src>, <dst>): [(<path>, <ports>), (<path_sec>, <ports_sec>]}
        _old_send (dict): Dictionary of old send inter-domain path instructions
            format: {<cid>: "{(<src>, <dst>): [{"action": <action>, "in": <in>, "out": <out>}, ...]
            If segment is start, instruction also has "out_addr" field and for end segment has "out_eth"

        _path_com_timer (Timer): Timer that is used to consolidate path computation
        _root_keep_alive_timer (Timer): Timer used to generate root controller keep alive messages
        _temp_speed (dict): Dictionary of inter-domain link speeds used when managing topo

        __send_lock (Lock): Lock for sending data using RabbitMQ
        __con_send (obj): RabbitMQ sending connection
        __con_recv (obj): RabbitMQ receive connection
        __chn_send (obj): RabbitMQ send channel
        __chn_recv (obj): RabbitMQ receive channel
    """
    HOST = "127.0.0.1"
    EXCHANGE = "SDN_Bridge"
    EXCHANGE_TYPE = "topic"

    # Number of seconds to wait for local controller keep alive before giving up
    CTRL_KEEP_ALIVE_TIME = 6
    # Number keep alives a local controller has to miss before they are dead
    CTRL_KEEP_ALIVE_COUNT = 1
    # Consolidation timer for inter-domain path computations (wait n seconds)
    PATH_COMP_TIME = 1
    # Send root controller keep alives every n seconds
    ROOT_KEEP_ALIVE_TIME = 30


    def __init__(self, logger, te_candidate_sort_rev=True, te_paccept=False):
        """ Initiate a new root controller instance """
        self.logger = logger
        self.te_candidate_sort_rev = te_candidate_sort_rev
        self.te_partial_accept = te_paccept

        self._ctrls = {}
        self._topo = {}
        self._graph = Graph()
        self._old_paths = {}
        self._old_send = {}
        self._temp_speed = {}
        self._path_comp_timer = None
        self._root_keep_alive_timer = None

        self.__send_lock = Lock()
        self.__con_send = None
        self.__com_recv = None
        self.__chn_send = None
        self.__chn_recv = None

    def start(self):
        """ Start the root controller by initiating the communication channel and block in a RabbitMQ
        receive loop.
        """
        # Establish a RabbitMQ connection and start the channel
        self.__com_recv = pika.BlockingConnection(pika.ConnectionParameters(host=self.HOST))
        self.__con_send = pika.BlockingConnection(pika.ConnectionParameters(host=self.HOST))
        self.__chn_recv = self.__com_recv.channel()
        self.__chn_send = self.__con_send.channel()

        self.__chn_recv.exchange_declare(exchange=self.EXCHANGE, exchange_type=self.EXCHANGE_TYPE,
                                        auto_delete=True)
        res = self.__chn_recv.queue_declare("", exclusive=True)
        queue_name = res.method.queue

        # Subscrive to the messages we want to recive
        self.__chn_recv.queue_bind(exchange=self.EXCHANGE, queue=queue_name,
                                    routing_key="root.c.discover")
        self.__chn_recv.queue_bind(exchange=self.EXCHANGE, queue=queue_name,
                                    routing_key="root.c.inter_domain.*")
        self.__chn_recv.queue_bind(exchange=self.EXCHANGE, queue=queue_name,
                                    routing_key="root.c.topo")

        # Request the topo from all local controllers and initiate the keep alive timer
        send_obj = {"msg": "get_topo"}
        self._safe_send("c.all", send_obj)
        self._init_root_keep_alive_timer()

        # Listen for messages
        self.logger.info("Started root controller")
        self.__chn_recv.basic_consume(queue=queue_name, on_message_callback=self.receive_callback,
                                        auto_ack=True)
        self.__chn_recv.start_consuming()

    def stop(self):
        """ Stop the RabbitMQ connections and cancel any timers that are still runnint """
        if self.__chn_recv is not None and self.__chn_recv.is_open:
            self._safe_cmd(self.__chn_recv.close)
        if self.__chn_send is not None and self.__chn_send.is_open:
            self._safe_cmd(self.__chn_send.close)
        if self.__com_recv is not None and self.__com_recv.is_open:
            self._safe_cmd(self.__com_recv.close)
        if self.__con_send is not None and self.__con_send.is_open:
            self._safe_cmd(self.__con_send.close)

        self.logger.info("Stopping running timers")
        for cid,cdat in self._ctrls.iteritems():
            if cdat["timer"] is not None:
                cdat["timer"].cancel()

        if self._path_comp_timer is not None:
            self._path_comp_timer.cancel()

        if self._root_keep_alive_timer is not None:
            self._root_keep_alive_timer.cancel()

    def receive_callback(self, chn, method, properties, body):
        """ Handler for recived root controller messages. Process the request and perform the
        required operation.
        """
        # Un-pickle the object data
        obj = None
        try:
            obj = pickle.loads(body)
        except pickle.UnpicklingError:
            self.logger.error("Could not un-pickle object, skipping ...")
            self.logger.error("Body: %s" % body)
            return

        # If there is no CID, malformed repsonse
        if "cid" not in obj:
            self.logger.error("Malformed object received, every call needs to have a CID")
            self.logger.error("Object: %s" % obj)
            return

        # Check if a new controller has been discovered
        cid = obj["cid"]
        if cid not in self._ctrls:
            # XXX: Do not trigger a path recomputation if we found a new ctrl as we
            # don't know how it connects to the other switches. Deffer any updates
            # unitl the unknown link advertisment by the controller that connected
            self.logger.info("Discovered a new controller with ID: %s" % cid)
            self.logger.debug("Controllers dictionary: %s" % self._ctrls)
            self._topo[cid] = {"hosts": [], "switches": [], "neighbours": {}, "te_thresh": 0}

        # Initiate or reset the keep alive timer for the local controller
        self._init_keep_alive_timer(cid)

        recomp_path = False
        if method.routing_key == "root.c.topo":
            # Topology from local controller received
            if self._action_topo(obj):
                recomp_path = True
        elif method.routing_key == "root.c.discover":
            # Local controller discovery message received
            self._action_discover(obj)
        elif method.routing_key == "root.c.inter_domain.unknown_sw":
            # CID inter-domain resolution request
            if self._action_unknown_sw(obj):
                recomp_path = True
        elif method.routing_key == "root.c.inter_domain.dead_port":
            # Local controller notified us of a dead inter-domain link/port
            if self._action_dead_port(obj):
                recomp_path = True
        elif method.routing_key == "root.c.inter_domain.link_traffic":
            # Received inter-domain link traffic from a local controller
            self._action_inter_domain_link_traffic(obj)
        elif method.routing_key == "root.c.inter_domain.congestion":
            # Received inter_domain link congestion message from controller
            self._action_inter_domain_link_congested(obj)
        elif method.routing_key == "root.c.inter_domain.egress_change":
            # Received a egress change notification from the local controller
            self._action_egress_change(obj)
        # Is this a inter-domain path ingress change notification?
        elif method.routing_key == "root.c.inter_domain.ingress_change":
            # Received a ingress change notification from the local controller
            self._action_ingress_change(obj)
        else:
            # Anything else is a unknown message and should be ignored
            self.logger.warning("Unknown message received from %s" % cid)
            self.logger.debug("Object: %s" % obj)

        # If the topology was modified, recompute the controller paths
        if recomp_path:
            self.logger.info("Data associated with controller changed, recomputing paths")
            self._init_path_comp_timer()

            self.logger.debug("-" * 40)
            self.logger.debug("Topo: %s" % self._topo)
            self.logger.debug("Graph: %s" % self._graph.topo)
            self.logger.debug("-" * 40)


    # ----------- ACTION HANDLERS ----------


    def _action_topo(self, obj):
        """ Process a topology receive action request by going through and adding the
        domain details to the objects.

        Args:
            obj (dict): Topology action object received from controller

        Returns:
            bool: True if we need to re-compute inter-domain paths, false otherwise
        """
        cid = obj["cid"]
        recomp_path = False

        # Add new hosts to the controller info
        for h in obj["hosts"]:
            if h not in self._topo[cid]["hosts"]:
                recomp_path = True
                self._topo[cid]["hosts"].append(h)

                # Add the host to the topology using a virtual link
                virtual_pn = self._gen_dom_virt_port(cid)
                self._graph.add_link(cid, h[0], virtual_pn, -1)
                self._graph.add_link(h[0], cid, -1, virtual_pn)

        # Remove any hosts from the controller info and graph (if no longer exists)
        for h in self._topo[cid]["hosts"]:
            if h not in obj["hosts"]:
                recomp_path = True
                self._topo[cid]["hosts"].remove(h)
                self._graph.remove_host(h[0])
                self.logger.info("Deleted host %s from cid %s" % (h, cid))

        # Add any new switches to the controller info
        for s in obj["switches"]:
            if s not in self._topo[cid]["switches"]:
                recomp_path = True
                self._topo[cid]["switches"].append(s)

        # Remove switches that no longer exist from the controller info
        for s in self._topo[cid]["switches"]:
            if s not in obj["switches"]:
                self._topo[cid]["switches"].remove(s)
                self.logger.info("Deleted switch %s from cid %s" % (s, cid))

        # XXX: Hmm, there is an explicit link dead message, we don't really need to
        # perform the same check as the hosts to see if we have unknown links that went
        # away because we are explicitly notified!
        for n,n_cid in obj["unknown_links"].iteritems():
            # Save the speed of the link to the temp array
            self._temp_speed[(n[0], n[1])] = n[3]

            # If this unknown link is a timer ignore it
            if isinstance(n_cid, list):
                continue

            # Add the switch to the topology object
            if self._add_cid_neighbour(cid, n_cid, n[0], n[1], n[2]) == True:
                recomp_path = True

        # Save the te threshold and restore the old installed paths
        self._topo[cid]["te_thresh"] = obj["te_thresh"]
        inter_dom_paths = obj.get("paths", {})
        if len(inter_dom_paths) > 0:
            self._old_send[cid] = inter_dom_paths

        return recomp_path

    def _action_discover(self, obj):
        """ Process a local controller discovery message.

        Args:
            obj (dict): Message object received from controller
        """
        # XXX: We already reset or initiated the controller so no need to do it again!
        cid = obj["cid"]
        self.logger.debug("Received controller discovery message from %s" % cid)
        self.logger.debug("TE-Threshold: %s" % obj["te_thresh"])
        self._topo[cid]["te_thresh"] = obj["te_thresh"]

    def _action_unknown_sw(self, obj):
        """ Process a unknown switch request from a local controller.

        Args:
            obj (dict): Request object received from controller

        Returns:
            bool: True if an inter-domain path computation needs to occur, false otherwise
        """
        cid = obj["cid"]
        recomp_path = False
        self.logger.info("Received unknown switch message from %s" % cid)
        self.logger.debug("Object: %s" % obj)

        if "speed" in obj:
            self._temp_speed[(obj["sw"], obj["port"])] = obj["speed"]

        # Find the CID of the unknown switch, if found send response to local controller
        n_cid = self._find_sw_cid(obj["dest_sw"])
        if n_cid is not None:
            self.logger.info("Switch belongs to CID %s" % n_cid)

            # Resend response to requestor
            obj["cid"] = n_cid
            obj["msg"] = "unknown_sw"
            self._safe_send("c.%s" % cid, obj)

            # Add the switch to the topology object
            if self._add_cid_neighbour(cid, n_cid, obj["sw"], obj["port"], obj["dest_sw"]) == True:
                recomp_path = True

        return recomp_path

    def _action_dead_port(self, obj):
        """ Process a dead port message from a local controller. Received when a inter-domain link/port
        of a local controller has died.

        Args:
            obj (dict): Request object received from controller
        """
        cid = obj["cid"]
        recomp_path = False
        self.logger.info("Received dead inter-domain port message from %s" % cid)
        self.logger.debug("Object: %s" % obj)
        self.logger.critical("XXXEMUL,%f,dead_idp,%s,%s:%s" % (time.time(), cid,
                                                    obj["sw"], obj["port"]))

        # Remove the link from the topology dictionary
        # XXX: Assume bidirectional failure when we receive a single failure
        src_sw = obj["sw"]
        src_pn = obj["port"]
        dst_sw = None
        dst_pn = None
        dst_cid = None
        found_neighbour = False
        for n in self._topo[cid]["neighbours"]:
            if n[1] == src_sw and n[2] == src_pn:
                dst_cid = n[0]
                dst_sw = self._topo[cid]["neighbours"][n]["switch"]
                dst_pn = self._topo[cid]["neighbours"][n]["port"]

                del self._topo[cid]["neighbours"][n]
                rev_n = (cid, dst_sw, dst_pn)

                if rev_n in self._topo[dst_cid]["neighbours"]:
                    del self._topo[dst_cid]["neighbours"][rev_n]
                found_neighbour = True
                break

        if found_neighbour == False:
            self.logger.info("Could not find neighbour for CID!")
        else:
            # Remove the source port of the dead inter-domain link
            if src_sw not in self._graph.topo or src_pn not in self._graph.topo[src_sw]:
                self.logger.info("Could not find src %s (%s) in graph topology to remove" % (src_sw, src_pn))
            else:
                del self._graph.topo[src_sw][src_pn]

            # Remoive the destination port of the dead inter-domain link
            if dst_sw not in self._graph.topo or dst_pn not in self._graph.topo[dst_sw]:
                self.logger.info("Could not find dst %s (%s) in graph topology to remove" % (dst_sw, dst_pn))
            else:
                del self._graph.topo[dst_sw][dst_pn]

            self.logger.info("Removed inter domain link %s (%s) -> %s (%s)" % (src_sw, src_pn, dst_sw, dst_pn))

            # XXX: Should we also remove the switch if it has only the connection to the GID ??
            # Recompute the links on next path computation (topo stale)
            recomp_path = True
            self._graph.topo_stale = True

        return recomp_path

    def _action_inter_domain_link_traffic(self, obj):
        """ Process an inter-domain link traffic update message received from a local controller. If
        the port exists in the topology update it's TX-rate.

        Args:
            obj (dict): Local controller message
        """
        cid = obj["cid"]
        self.logger.debug("Got IDL traff from %s (traff_bps: %s)" %
                                                (cid, obj["traff_bps"]))
        pinfo = self._graph.get_port_info(obj["sw"], obj["port"])
        if pinfo is not None:
            tx_bytes = obj["traff_bps"] / 8.0
            self._graph.update_port_info(
                obj["sw"], obj["port"], tx_bytes=tx_bytes, is_total=False
            )

    def _action_inter_domain_link_congested(self, obj):
        """ Process a congested inter-domain link message received from a local controller. Update
        the links TX bytes and perform a TE optimisation of the paths to resolve the congestion.

        Args:
            obj (dict): Message received from local controller
        """
        cid = obj["cid"]
        self.logger.info("Received inter domain link congestion message from %s" % cid)
        self.logger.debug("Object: %s" % obj)

        # If the port exists in the graph update the TX Rate
        pinfo = self._graph.get_port_info(obj["sw"], obj["port"])
        if pinfo is not None:
            tx_bytes = obj["traff_bps"] / 8.0
            self._graph.update_port_info(
                obj["sw"], obj["port"], tx_bytes=tx_bytes, is_total=False
            )
        else:
            self.logger.error("Congested port %s (%s) dosen't exist!" %
                                                    (obj["sw"], obj["port"]))
            return

        # Initiate the optimisation procedure
        self._te_optimisation(obj)

        # Send a notification to the local controller that the TE optimisation finished
        send_obj = {"msg": "processed_con", "sw": obj["sw"], "port": obj["port"]}
        self._safe_send("c.%s" % obj["cid"], send_obj)

    def _action_egress_change(self, obj):
        """ Process an egress change notification from a local controller """
        cid = obj["cid"]
        self.logger.info("Received inter domain path egress change notification %s" % cid)
        self.logger.debug("Object: %s" % obj)
        self._path_info_changed(obj)

    def _action_ingress_change(self, obj):
        """ Process an ingress change notification from the local controller """
        cid = obj["cid"]
        self.logger.info("Received inter domain path ingress change notification %s" % cid)
        self.logger.debug("Object: %s" % obj)
        self._path_info_changed(obj)

    def __find_path(self, g, hkey_src, hkey_dst):
        """ Find a path that only visites domains once. Method works by computing a
        shortest path and checking if we visit a domain more than once. If the path
        is invalid, the link that leads back to the domain we re-visited is removed
        and the process repeats.

        XXX FIXME: Reconsider this as we may restrict our path computation. What if
        we remove a link that no longer leads to a already visited domain and can
        be used to compute the shortest path? Maybe keep track of domains and based
        on this clean the topology? This may lead to infinite loops though ...

        Args:
            g (graph): Topology graph to use.
            hkey_src (str): Key of source to compute path from
            hkey_dst (srt): Key of destination to compute path to

        Returns:
            (list, list): List of path nodes, list of path ports
        """
        # Make a copy of the topology to preserve links
        g = Graph(g.topo)

        while True:
            found = True
            path = g.shortest_path(hkey_src, hkey_dst)
            ports = g.flows_for_path(path)
            if len(path) == 0:
                return [], []

            visited_cids = []
            last_cid = None
            for i in range(len(ports)-1):
                node = ports[i+1]
                cid = self._belongs_to_cid(node[0])[0]
                if last_cid is None:
                    last_cid = cid

                if not last_cid == cid:
                    if cid in visited_cids:
                        found = False
                        node_prev = ports[i]
                        src = node_prev[0]
                        dst = node[0]
                        src_pn = node_prev[2]
                        dst_pn = node[1]
                        self.logger.info("Path goes back to visited domain %s | %s-%s | %s -> %s" %
                                            (cid, src, dst, node, node_prev))
                        self.logger.debug("Remove link %s (%s) - %s (%s)" % (src, src_pn, dst, dst_pn))
                        if not g.remove_port(src, dst, src_pn, dst_pn):
                            self.logger.critical("Can't remove link (fix domain revisit)!")
                            return [], []
                        break
                    visited_cids.append(last_cid)
                    last_cid = cid

            if found:
                return path, ports

    def _compute_inter_domain_paths(self):
        """ Compute inter-domain paths notifying controllers to compute and remove segmnets """
        self.logger.critical("XXXEMUL,%f,comp_path" % time.time())

        # Prune the current topology of inactive controllers
        # XXX: This allows dealing with CTRL CID changes due to a restart.
        g = self._prune_topo_inactive_cids(self._graph)

        # Clear the old paths dictionary (will be overwritten with new paths)
        self._old_paths = {}

        self.logger.info("Computing inter domain paths")
        send = {}
        for fcid,fcid_data in self._topo.iteritems():
           for scid,scid_data in self._topo.iteritems():
                # Do not compute paths to our own domain
                if fcid == scid:
                    continue

                # Compute a path from every pair
                for fh in fcid_data["hosts"]:
                    for sh in scid_data["hosts"]:
                        if fh == sh:
                            continue

                        # Make a copy of the topology (will modify weights)
                        gn = Graph(g.topo)
                        path, ports = self.__find_path(gn, fh[0], sh[0])

                        # If the computed path is empty do not process any further
                        if len(path) == 0:
                            continue
                        res_path = [(path, ports)]
                        ports_list = [ports]

                        # Compute a secondary minimally overlapping path
                        for i in range(len(ports)-1):
                            src = ports[i][0]
                            dst = ports[i+1][0]
                            src_port = ports[i][2]
                            dst_port = ports[i+1][1]
                            gn.change_cost(src, dst, src_port, dst_port, 100000)

                        path_sec, ports_sec = self.__find_path(gn, fh[0], sh[0])
                        if len(path_sec) > 0:
                            res_path.append((path_sec, ports_sec))
                            ports_list.append(ports_sec)
                        self._old_paths[(fh[0], sh[0])] = res_path

                        # Process the compacted path to domain instructions in the send dict
                        self._path_to_instructions(fh, sh, ports_list, send)

        # Go through the new path changes and compute difference we need to install
        for cid,cid_paths in send.iteritems():
            self.logger.info("Sending path request to %s" % cid)

            # If this CID is new copy the paths to the old_send
            if cid not in self._old_send:
                self._old_send[cid] = cid_paths

                for hkey,paths in cid_paths.iteritems():
                    self.logger.debug("(%s) %s" % (hkey, paths))
                    self.logger.debug("New CID, installing unconditionally")
            else:
                remove = []
                old_remove = []

                # Find paths that have already been installed and remove them or add new/changed
                # paths to the old paths dictionary
                for hkey,paths in cid_paths.iteritems():
                    self.logger.debug("(%s) %s" % (hkey, paths))

                    # Check if the path is the same as the already installed one
                    if self._path_already_installed(cid, hkey, paths):
                        self.logger.debug("Path already installed, not re-sending!")
                        remove.append(hkey)
                    else:
                        self.logger.debug("Path changed, sending details")
                        self._old_send[cid][hkey] = paths

                # Iterate through old paths and see if any need to be removed
                for hkey,paths in self._old_send[cid].iteritems():
                    if hkey not in cid_paths:
                        self.logger.debug("(%s) %s" % (hkey, paths))
                        self.logger.debug("Removing path that no longer exists")
                        for path in paths:
                            path["action"] = "delete"
                        cid_paths[hkey] = paths
                        old_remove.append(hkey)

                # Delete the paths from the send and old list
                for hkey in remove:
                    del cid_paths[hkey]
                for hkey in old_remove:
                    del self._old_send[cid][hkey]

            # Send the new path instructions to the local controller, if any exist
            if len(cid_paths) > 0:
                send_obj = {"msg": "compute_paths", "paths": cid_paths}
                self._safe_send("c.%s" % cid, send_obj)

        # Go through the old paths and remove paths from controllers that non longer exist
        # in new paths dictionary
        old_remove = []
        for cid,cid_paths in self._old_send.iteritems():
            if cid not in send:
                self.logger.info("CID %s no longer has paths, removing all previously installed paths" % cid)
                for hkey,paths in cid_paths.iteritems():
                    self.logger.debug("(%s) %s" % (hkey, paths))
                    for path in paths:
                        path["action"] = "delete"

                send_obj = {"msg": "compute_paths", "paths": cid_paths}
                self._safe_send("c.%s" % cid, send_obj)
                old_remove.append(cid)

        # Remove the deleted paths from the old sent paths dictionary
        for cid in old_remove:
            del self._old_send[cid]

        self.logger.info("-" * 40)
        self._write_controller_state()

    def _path_info_changed(self, obj):
        """ Process a path information change caused by either a egress or an ingress change.
        The method will modify both `:mod:attr:(old_send)` and `:mod:attr:(paths)` to reflect
        the new ingress and egress values.

        Args:
            obj (obj): Egress or Ingress change object that contains the new paths
        """
        cid = obj["cid"]
        hkey = obj["hkey"]
        old_gen_paths_info = self._old_send[cid][hkey]
        old_gen_paths = self._old_paths[hkey]
        new_gen_paths_info = obj["new_paths"]

        # Check if this CID is a start, transit or end
        seg_type = ""
        if not isinstance(old_gen_paths_info[0]["in"], tuple):
            seg_type = "start"
        elif not isinstance(old_gen_paths_info[0]["out"], tuple):
            seg_type = "end"
        else:
            seg_type = "transit"

        # Swap over the old sent path information with the new info
        self._old_send[cid][hkey] = new_gen_paths_info

        # Iterate through the path information and fix the paths and ports list
        for i in range(len(new_gen_paths_info)):
            old_pinfo = old_gen_paths_info[i]
            pinfo = new_gen_paths_info[i]

            for q in range(len(old_gen_paths[i][0])):
                node = old_gen_paths[i][0][q]
                if not seg_type == "start" and node == old_pinfo["in"][0]:
                    old_gen_paths[i][0][q] = pinfo["in"][0]

                if not seg_type == "end" and node == old_pinfo["out"][0]:
                    old_gen_paths[i][0][q] = pinfo["out"][0]

            for q in range(len(old_gen_paths[i][1])):
                node = old_gen_paths[i][1][q]
                if not seg_type == "start" and node[0] == old_pinfo["in"][0] and node[1] == old_pinfo["in"][1]:
                    #other_port = self._graph.get_port_info(pinfo["in"][0], pinfo["in"][1])
                    old_gen_paths[i][1][q] = (pinfo["in"][0], pinfo["in"][1], node[2])

                if not seg_type == "end" and node[0] == old_pinfo["out"][0] and node[2] == old_pinfo["out"][1]:
                    #other_port = self._graph.get_port_info(pinfo["out"][0], pinfo["out"][1])
                    old_gen_paths[i][1][q] = (pinfo["out"][0], node[1], pinfo["out"][1])

        self._write_controller_state()

    def _ctrl_dead(self, cid):
        """ Callback method called when the controller time-out timer expires. If the controller
        did not respond to `mod:attr:(CTRL_KEEP_ALIVE_COUNT)` keep alive intervals the controller
        is timed out (controller data is removed).

        Args:
            cid (int): Controller ID for the controller that did not send a keep-alive
        """
        self._ctrls[cid]["count"] += 1
        if self._ctrls[cid]["count"] >= self.CTRL_KEEP_ALIVE_COUNT:
            # Time out the controller
            self.logger.info("Controller with ID %s timed-out!" % cid)
            self.logger.critical("XXXEMUL,%f,dead_ctrl,%s" % (time.time(), cid))

            # Remove the hosts of the dead CID
            for h in self._topo[cid]["hosts"]:
                h = h[0]
                if h in self._graph.topo:
                    rem_pn = []
                    for p,p_data in self._graph.topo[h].iteritems():
                        dest_sw = p_data["dest"]
                        dest_pn = p_data["destPort"]
                        # Delete link if it points to dead ctrl
                        if dest_sw == cid:
                            del self._graph.topo[dest_sw][dest_pn]
                            rem_pn.append(p)

                    # Remove all ports beloging to dead CID
                    for r in rem_pn:
                        del self._graph.topo[h][r]

                    # Remove the host if it no longer has links
                    if len(self._graph.topo[h]) == 0:
                        del self._graph.topo[h]

            # Remove the switches of the dead CID
            for sw in self._topo[cid]["switches"]:
                if sw in self._graph.topo:
                    connected_other_cid = False
                    rem_pn = []
                    for p,p_data in self._graph.topo[sw].iteritems():
                        dest_sw = p_data["dest"]
                        dest_pn = p_data["destPort"]
                        if dest_sw == cid:
                            # Delete the other end of the link and queue the port for removal
                            del self._graph.topo[dest_sw][dest_pn]
                            rem_pn.append(p)
                        elif dest_sw in topo:
                            # We found a connection to antother CID, possible duplicate
                            # CTRLS managing same objects
                            connected_other_cid = True

                # Remove all ports that belong to the dead CID
                for r in rem_pn:
                    del self._graph.topo[sw][r]

                # If the switch does not connect to another CID delete it (it's dead)
                if not connected_other_cid:
                    for p,p_data in self._graph.topo[sw].iteritems():
                        # Delete the othe rend of the link
                        dest_sw = p_data["dest"]
                        dest_pn = p_data["destPort"]
                        del self._graph.topo[dest_sw][dest_pn]
                    # Delete the switch object
                    del self._graph.topo[sw]

            # Remove the dead CID node from the topology
            if cid in self._graph.topo:
                del self._graph.topo[cid]

            # Remove the neighbour details that reference the dead CID
            for n_cid, n_cid_data in self._topo.iteritems():
                remove = []
                for n in n_cid_data["neighbours"]:
                    if n[0] == cid:
                        remove.append(n)
                for r in remove:
                    del n_cid_data["neighbours"][r]

            # Mark topo stale, remove dead ctrl info and recompute the paths
            self._graph.topo_stale = True
            del self._ctrls[cid]
            del self._topo[cid]
            self._init_path_comp_timer()

            # Inform all local controllers of the controller that died (they should remove
            # their unknown link mappings)
            send_obj = {"msg": "ctrl_dead", "cid": cid}
            self._safe_send("c.all", send_obj)
        else:
            # Restart the timer, still have counts avaiable
            self.logger.info("Did not receive keep alive from CID %s (count %s)" %
                                (cid, self._ctrls[cid]["count"]))
            self._init_keep_alive_timer(cid, self._ctrls[cid]["count"])


    # ----------- TE OPTIMISATION METHODS ----------


    def _te_optimisation(self, obj):
        """ Process a TE optimisation request from a local controller. Root
        controller uses the CSPFRecomp method from the standard TE
        optimisation module. See ```TE.py:__findPotentialPath_CSPFRecomp```
        for more details on how algorithm works. If a valid solution is
        identified, the algorithm will send new path instalation requests
        to the relevant local controllers to install the new path changes.

        Args:
            obj (dict): Info received from local controller which contains
                congested port details and a list of candidates that
                use the port
        """
        self.logger.info("Root TE Optimisation Called")
        self.logger.info("\tCandidate Sort Rev: %s" % self.te_candidate_sort_rev)
        self.logger.info("\tPartial Accept: %s" % self.te_partial_accept)
        self.logger.info("-----------------------------")

        # Get relevant info and make copy of root controller topology
        g = Graph(self._graph.topo)
        pinfo = g.get_port_info(obj["sw"], obj["port"])
        con_capacity = pinfo["speed"]
        con_usage_bps = obj["traff_bps"]
        con_max_traff = con_capacity * obj["te_thresh"]
        con_spare_of_cap = con_capacity - con_usage_bps

        # Go through the received list of candidates and check which are
        # valid (we have an existing inter-domain path computed and use
        # the congested port). If any candidate is invalid, reduce the
        # overall bps on the congested port and do not add to candidate set.
        candidates = []
        for c,c_usage in obj["paths"]:
            if c not in self._old_paths:
                # Do not have path for candidate, reduce congestion usage
                self.logger.critical("Can't find candidate %s-%s path" % c)
                con_usage_bps -= candidate_bps
                continue

            old_ports = self._old_paths[c][0][1]
            if not self._link_in_path(old_ports, obj["sw"], obj["port"]):
                # Candidate does not use congested port, reduce usage
                self.logger.critical("Candidate %s-%s doesn't use con port" % c)
                con_usage_bps -= c_usage
                continue

            # Candidate is valid, add to list of candidates
            candidates.append((c, c_usage))

        # Sort the list of candades based on the part sort flag direction
        candidates = sorted(candidates, key=lambda util:util[1],
                                        reverse=self.te_candidate_sort_rev)

        # Iterate through candidates to find solution to congestion
        mod = []
        for c,c_usage in candidates:
            # If the port is no longer congested, stop iterating through
            # candidates
            if con_usage_bps <= con_max_traff:
                self.logger.critical("Port is no longer congested!")
                break

            # Get the candidate details and perform a CSPF prune of the topo
            c_path = self._old_paths[c][0][0]
            c_ports = self._old_paths[c][0][1]
            c_tx_bytes = c_usage / 8.0
            self.logger.info("Pair %s | TX bps %s" % (c, c_usage))

            g_tmp = Graph(g.topo)
            CSPFPrune(g_tmp, (obj["sw"], obj["port"]), c_path, c_usage,
                                    self.logger, poll_rate=1,
                                    te_thresh_method=self._get_cid_te_thresh,
                                    paccept=self.te_partial_accept)

            # Try to recompute a new potential path for the candidate
            pot_path, pot_ports = self.__find_path(g_tmp, c[0], c[1])
            if len(pot_path) > 0:
                # Found a valid potential path, save details and increment
                # traffic on temporary topology (not global)
                self.logger.info("Found a valid potential path for candidate"
                                                                " %s-%s" % c)
                self.logger.debug("\tPath: %s" % pot_path)
                con_usage_bps -= c_usage

                mod.append((c, c_ports, pot_ports, c_path, pot_path,
                                                                c_tx_bytes))
                self.logger.info("Reduces con to %s (%s)" % (con_usage_bps,
                                                            con_max_traff))

                update_link_traffic(g, c_ports, pot_ports, c_tx_bytes,
                                                                self.logger)

        # XXX: -------- CHECK THE SOLUTION SET AND APPLY IF OK --------


        # Check if solution set is invalid
        found_valid_partial = False
        invalid_solution_set = False
        if len(mod) > 0 and self.te_partial_accept:
            # Get the min spare capacity of solution set (new links used)
            min_spare = find_solset_min_spare_capacity(g, mod,
                            self.logger,
                            te_thresh_method=self._get_cid_te_thresh)
            self.logger.info("CON PORT INIT SPARE: %s | NEW SPARE: %s" %
                                    (con_spare_of_cap, str(min_spare)))

            # If the solution set introduces new congestion without loss,
            # invalidate it if the new minimum spare capcity is less than
            # the original congested port spare capcity (we introduced more
            # congestion).
            if min_spare[0] < 0 and min_spare[1] <= con_spare_of_cap:
                self.logger.info("Solset introduces more congestion."
                                    " Invalidating solution set!")
                invalid_solution_set = True

            # Check if we have a valid partial solution. A partial sol
            # is a set of modifications that causes congestion over the
            # te-threshold but does not cause congestion loss to occur.
            if (not invalid_solution_set and
                                    con_usage_bps > con_max_traff and
                                    con_usage_bps <= con_capacity):
                self.logger.info("\t Valid partial solution!")
                found_valid_partial = True

        # If no valid solution found, exit the method
        if (not len(mod) > 0 or invalid_solution_set or (con_usage_bps >
                                con_max_traff and not found_valid_partial)):
            self.logger.info("Could not resolve con for sw %s port %s" %
                                                (obj["sw"], obj["port"]))
            return

        # Found a fix to resolve congestion, apply all the changes
        self.logger.info("Found a fix for the congested sw %s port %s" %
                                                    (obj["sw"], obj["port"]))


        # Porcess the path modifications (and update the old path)
        # XXX: Currently the secondary path is defined as the old primary
        # path (with congestion). Maybe it would be wise to re-compute another
        # secondary path, however, this has the chance of being quite long
        # compared to the old primary. Regardless of conditions, the secondary
        # path will only be used for a short period of time when failures occur.
        send = {}
        for mod_info in mod:
            c, ports_sec, ports, path_sec, path, _ = mod_info
            c, c_ports, pot_ports, c_path, pot_path, _ = mod_info
            src_cid = pot_path[1]
            dst_cid = pot_path[len(pot_path)-2]
            fh = None
            sh = None
            for h in self._topo[src_cid]["hosts"]:
                if h[0] == pot_path[0]:
                    fh = h
                    break

            for h in self._topo[dst_cid]["hosts"]:
                if h[0] == pot_path[len(path)-1]:
                    sh = h
                    break

            # Update the old paths and generate the domain path instructions
            self._old_paths[c] = [(pot_path, pot_ports), (c_path, c_ports)]
            self._path_to_instructions(fh, sh, [pot_ports, c_ports], send)

        # Go through the new path changes and compute differences we need to install
        for cid,cid_paths in send.iteritems():
            self.logger.info("Sending path request to %s" % cid)

            # If this CID is new copy the paths to the old_send
            if cid not in self._old_send:
                self._old_send[cid] = cid_paths

                for hkey,paths in cid_paths.iteritems():
                    self.logger.debug("(%s) %s" % (hkey, paths))
                    self.logger.debug("New CID, installing unconditionally")
            else:
                remove = []
                old_remove = []

                # Find paths that have already been installed and remove them or add new/changed
                # paths to the old paths dictionary
                for hkey,paths in cid_paths.iteritems():
                    self.logger.debug("(%s) %s" % (hkey, paths))

                    # Check if the path is the same as the already installed one
                    if self._path_already_installed(cid, hkey, paths):
                        self.logger.debug("Path already installed, not re-sending!")
                        remove.append(hkey)
                    else:
                        self.logger.debug("Path changed, sending details")
                        self._old_send[cid][hkey] = paths

                # Iterate through old paths and see if any need to be removed
                for hkey,paths in self._old_send[cid].iteritems():
                    if hkey not in mod:
                        continue

                    if hkey not in cid_paths:
                        self.logger.debug("(%s) %s" % (hkey, paths))
                        self.logger.debug("Removing path that no longer exists")
                        for path in paths:
                            path["action"] = "delete"
                        cid_paths[hkey] = paths
                        old_remove.append(hkey)

                # Delete the paths from the send and old list
                for hkey in remove:
                    del cid_paths[hkey]
                for hkey in old_remove:
                    del self._old_send[cid][hkey]

            # Send the new path instructions to the local controller, if any exist
            if len(cid_paths) > 0:
                send_obj = {"msg": "compute_paths", "paths": cid_paths}
                self._safe_send("c.%s" % cid, send_obj)

        # FIXME TODO XXX: IS THE FOLLOWING BROKEN ??? WILL THIS REMOVE CIDS THAT IT SHOULDN'T

        # Go throgh the old paths and remove paths form controllers which are
        # no longer used (not in new path dictionary)
        old_remove = []
        for cid,cid_paths in self._old_send.iteritems():
            old_hkey_remove = []
            rem_send = {}
            if cid not in send:
                self.logger.info("CID %s not in path mod for TE opti, checking old paths to remove" % cid)
                for hkey,paths in cid_paths.iteritems():
                    if hkey not in mod:
                        continue

                    self.logger.debug("(%s) %s" % (hkey, paths))
                    for path in paths:
                        path["action"] = "delete"
                    rem_send[hkey] = paths
                    old_hkey_remove.append(hkey)

                send_obj = {"msg": "compute_paths", "paths": rem_send}
                self._safe_send("c.%s" % cid, send_obj)

                # Remove the path from the old installed dict
                for hkey in old_hkey_remove:
                    del cid_paths[hkey]

                # If the CID has no more paths add it to be deleted
                if len(cid_paths) == 0:
                    old_remove.append(cid)

        # Remove any CIDs that no longer have paths
        for cid in old_remove:
            del self._old_send[cid]

        # Update the traffic on the global topology graph
        for mod_info in mod:
            c, c_ports, pot_ports, c_path, pot_path, tx_bytes = mod_info
            update_link_traffic(self._graph, c_ports, pot_ports, tx_bytes,
                                                                self.logger)

        self.logger.info("-" * 40)
        self._write_controller_state()


    # ---------- CONTROLLER AND TOPOLOGY HELPER METHODS ----------


    def _ctrl_is_active(self, cid):
        """ Check if controller with ID `cid` is active (hasen't missed a keep alive). """
        if cid in self._ctrls:
            if self._ctrls[cid]["count"] > 0:
                return False
        return True

    def _gen_dom_virt_port(self, cid):
        """ Generate a virtual port for a domain. The port is created by decremeting a number (from -1)
        until a unique port is found in `:cls:attr:(graph)`.

        Args:
            cid (int): ID of the domain to generate port for

        Returns:
            int: Virtual port for the controller. If `CID` is invalid -1 is returned
        """
        port_num = -1
        while True:
            # If the controller dosen't exist in the topology just return
            if cid not in self._graph.topo:
                return port_num

            if port_num not in self._graph.topo[cid]:
                return port_num

            port_num -= 1

    def _gen_sw_virt_port(self, sw):
        """ Similar to ``_gen_dom_virt_port``, however, method works for a switch and not a domain node
        object.
        """
        port_num = -1
        while True:
            # If the controller dosen't exist in the topology just return
            if sw not in self._graph.topo:
                return port_num

            if port_num not in self._graph.topo[sw]:
                return port_num

            port_num -= 1

    def _belongs_to_cid(self, obj):
        """ Return the ID of the domain that a secific object belongs to. Method will search
        `:cls:attr:(topo)` to see if `obj` is a CID, host, or a switch. A complete list of all
        controller IDs that manage the element is returned.

        Args:
            obj (obj): Object to check what CID it belongs to.

        Returns:
            list: IDs of the domain that `obj` belongs to.
        """
        cids = []
        for cid,cid_info in self._topo.iteritems():
            if cid == obj:
                return [cid]

            # If this ctrl is not active (missed a keep alive request) ignore it
            # This allows dealing with ctrls restarting and using different CID
            if not self._ctrl_is_active(cid):
                continue

            for n in cid_info["hosts"]:
                if n[0] == obj:
                    cids.append(cid)
                    continue

            for sw in cid_info["switches"]:
                if sw == obj:
                    cids.append(cid)
                    continue

        return cids

    def _find_sw_cid(self, sw):
        """ Find the CID of the active controller that manages a switch. """
        for cid,cdata in self._topo.iteritems():
            # If this ctrl is not active (missed a keep alive request) ignore it
            # This allows dealing with ctrls restarting and using different CID
            if not self._ctrl_is_active(cid):
                continue
            if sw in cdata["switches"]:
                return cid
        return None

    def _find_neighbour(self, from_cid, find, from_sw, dest_sw):
        """ Search through the inter-domain links to find a specific neighbour.

            Args:
                from_cid (int): Target CID to search through it's neighbours
                find (int): CID of domain we are looking for
                from_sw (int): DPID of switch which connects to `dest_sw`
                dest_sw (int): DPID of switch which `from_cid` domain connects to

            Returns (triple, dict): None if neighbour dosen't exist, else key and dict entry
                of neighbour that matches
        """
        if from_cid not in self._topo:
            return (None, None)

        for fn,fn_data in self._topo[from_cid]["neighbours"].iteritems():
            if fn[0] == find and fn[1] == from_sw and fn_data["switch"] == dest_sw:
                return (fn, fn_data)
        return (None, None)

    def _get_cid_te_thresh(self, sw, port):
        """ Get the te-threshold attribute of the controller that manages
        the link defined by (`sw`, `port`).

        Args:
            sw (obj): Switch ID to identify controller
            port (obj): Port of the link (ignored)

        Returns:
            float: TE-threshold of the controller that manages the link
            identified by (`sw`, `port`).
        """
        for cid,cid_info in self._topo.iteritems():
            if cid == sw or sw in cid_info["switches"]:
                return cid_info["te_thresh"]
        return None

    def _add_cid_neighbour(self, cid, n_cid, src_sw, src_port, dst_sw):
        """ Add a neighbour link that connects `cid` to neighbouring domain `n_cid` using
        switch `src_sw` on port `src_port` to destination switch `dst_sw`.

        Args:
            cid (int): ID of the source domain
            n_cid (int): ID of the neighbouring domain
            src_sw (int): Switch that connects to the neighbouring domain
            src_port (int): Port of switch `src_sw` that connects to the neighbour
            dst_sw (int): Destination switch that `src_sw` connects to.

        Returns:
            bool: True if the path needs to be recomputed, false otherwise. A path will
                need to be recomputed only if we have established the neighbour details
                of the other end of the neighbour connection.
        """
        recomp_paths = False

        # Only process the information if we haven't seen the link before
        n_key = (n_cid, src_sw, src_port)
        if n_key not in self._topo[cid]["neighbours"]:
            self._topo[cid]["neighbours"][n_key] = {
                "switch": dst_sw,
                "port": None
            }

            # Add a link from the CID to the source switch if one dosen't exist
            src_find = self._graph.find_ports(cid, src_sw)
            if src_find is None:
                cid_vpn = self._gen_dom_virt_port(cid)
                sw_vpn = self._gen_sw_virt_port(src_sw)
                self._graph.add_link(cid, src_sw, cid_vpn, sw_vpn)
                self._graph.add_link(src_sw, cid, sw_vpn, cid_vpn)

            # Try to find the links other end details
            reverse_key, reverse_data = self._find_neighbour(n_cid, cid, dst_sw, src_sw)
            if reverse_data is not None:
                dst_port = reverse_key[2]
                self._topo[cid]["neighbours"][n_key]["port"] = dst_port
                reverse_data["port"] = src_port
                recomp_paths = True

                src_link = self._graph.get_port_info(src_sw, src_port)
                dst_link = self._graph.get_port_info(dst_sw, dst_port)

                if src_link is None:
                    if src_sw is not None and src_port is not None:
                        self._graph.add_link(src_sw, dst_sw, src_port, dst_port)
                        speed_key = (src_sw, src_port)
                        if speed_key in self._temp_speed:
                            self._graph.update_port_info(src_sw, src_port, speed=self._temp_speed[speed_key])
                else:
                    if dst_sw is not None and dst_port is not None:
                        src_link["destPort"] = dst_port

                if dst_link is None:
                    if dst_sw is not None and dst_port is not None:
                        self._graph.add_link(dst_sw, src_sw, dst_port, src_port)
                        speed_key = (dst_sw, dst_port)
                        if speed_key in self._temp_speed:
                            self._graph.update_port_info(dst_sw, dst_port, speed=self._temp_speed[speed_key])
                else:
                    if src_sw is not None and src_port is not None:
                        dst_link["destPort"] = src_port

        return recomp_paths

    def _prune_topo_inactive_cids(self, graph):
        """ Prune the current topology `:cls:attr:(graph)` returning a copy where inactive
        controllers have been removed. A dead controller is defined by ``_ctrl_is_active``.

        Args:
            graph (Graph): Graph instance to use for pruning (copy is made)

        Returns:
            Graph: Topology object without links leading to and from dead ctrls
        """
        g = Graph(graph.topo)
        rem = []
        for n,n_data in g.topo.iteritems():
            if n in self._topo and (not self._ctrl_is_active(n)):
                for p,p_data in g.topo[n].iteritems():
                    dest = p_data["dest"]
                    dest_pn = p_data["destPort"]
                    del g.topo[dest][dest_pn]
                rem.append(n)
        for r in rem:
            del g.topo[r]
        g.topo_stale = True
        return g


    # ---------- PATH HELPER METHODS ----------


    def _link_in_path(self, ports, sw, port):
        """ Iterate through a path ports list to check if the link `sw`, `port`
        exists.

        Args:
            ports (list): List of path ports to check for triple
            sw (int): Switch or object to check for
            port (int): Send port that described link source

        Returns:
            bool: True if the entry exists, false otherwise
        """
        for p in ports:
            if p[0] == sw and  p[2] == port:
                return True
        return False

    def _path_already_installed(self, cid, hkey, paths):
        """ Check if a path is already installed in `:cls:attr:(old_send)`.

        Args:
            cid (int): ID of the controller we need to serch for the paths
            hkey (tuple of str): Source destination pair of path
            paths (list): Array of paths to check if they exist

        Returns:
            bool: True if the path already exists, False otherwise
        """
        # Check the basic attributes
        if cid not in self._old_send:
            return False
        if hkey not in self._old_send[cid]:
            return False
        if not len(self._old_send[cid][hkey]) == len(paths):
            return False

        # Iterate through the paths and make sure they are the same
        for i in range(len(self._old_send[cid][hkey])):
            if (not paths[i]["in"] == self._old_send[cid][hkey][i]["in"] or
                not paths[i]["out"] == self._old_send[cid][hkey][i]["out"] or
                not paths[i].get("out_addr", None) == self._old_send[cid][hkey][i].get("out_addr", None) or
                not paths[i].get("out_eth", None) == self._old_send[cid][hkey][i].get("out_eth", None)):
                    return False

        # Everything matches
        return True

    def _path_to_instructions(self, fh, sh, ports_list, send):
        """ Process a list of paths for two hosts `fh` and `sh` into a dictionary of CID instructions
        to be sent to the local controllers to install the path. THe result will be stored in `send`.

        Note:
            Syntax of `send` will be { cid: {
                (src, dst): [ {"in": in_port, "out": out_port, "out_addr": out_addr, "out_eth": out_eth,
                                "action": action}, ... ]
            } }

            Where 'out_addr' is only present for the path start domain and 'out_eth' for the end domain.
            'action' sepcifies the action of the path which in this case is 'add'.

        Args:
            fh (tuple): Src host topo dictionary entry tuple that contains name, mac and IP.
            sh (tuple): Dest host topo dictionary entry tuple that contains name, mac and IP.
            ports_list (list): List of path ports where the first entry is the primary.
            send (dict): Target dictionary to store result from processed paths
        """
        # Key pair tuple
        hkey = (fh[0], sh[0])

        # Iterate through the paths and process them into send dict instructions
        for ports in ports_list:
            in_port = None
            out_port = None
            cid = None
            is_ingress = False

            # Go through all ports in the path
            for i in range(len(ports)):
                current_cid = self._belongs_to_cid(ports[i][0])
                if i == 0:
                    # Special case for the first port, obj is a CID so always one element
                    in_port = -1
                    cid = current_cid[0]
                    is_ingress = True

                # If this is a domain node just update the current CID
                # XXX: The code assumes that CID nodes can't connect to other CID nodes directly otherwise
                # the topology is toast. If we see a CID node just update the current CID, resolve a list of
                # for the current segment for which we may have incorrectly assumed the first node is correct
                if ports[i][0] in self._topo:
                    cid = ports[i][0]
                # If the path contains a new domain add instructions for the old domain
                elif cid not in current_cid:
                    out_port = (ports[i-1][0], ports[i-1][2])
                    obj = {"in": in_port, "out": out_port, "action": "add"}
                    if is_ingress:
                        is_ingress = False
                        obj["out_addr"] = sh[2]

                    if cid not in send:
                        send[cid] = {}

                    if hkey not in send[cid]:
                        send[cid][hkey] = [obj]
                    else:
                        # Only add the alternative path if it's not the same as the current path
                        if not obj in send[cid][hkey]:
                            send[cid][hkey].append(obj)

                    in_port = (ports[i][0], ports[i][1])

                    # XXX: Alaways assume the current CID is the first element, if we have a list and this
                    # is incorrect, the CID node ports triple will change this value and if we have switch
                    # to switch to switch, we just select one.
                    cid = current_cid[0]

            # Add the information for the final domain (method procs on domain change)
            obj = {"in": in_port, "out": -1, "action": "add", "out_eth": sh[1]}
            if cid not in send:
                send[cid] = {}

            if hkey not in send[cid]:
                send[cid][hkey] = [obj]
            else:
                # Only add the alternative path if it's not the same as the current path
                if not obj in send[cid][hkey]:
                    send[cid][hkey].append(obj)


    # ---------- TIMER HELPER METHODS ---------


    def _init_keep_alive_timer(self, cid, count=0):
        """ Start/Restart the local controller keep alive timer by canceling the previous instance
        and re-initiating it. Method will set the counter of the controller to `count`.

        Args:
            cid (int): ID of the controller to restart the counter of
            count (int): Current keep alive missed count. Defaults to 0 (reset timer).
        """
        if cid in self._ctrls and self._ctrls[cid]["timer"] is not None:
           self._ctrls[cid]["timer"].cancel()

        self._ctrls[cid] = {"timer": Timer(self.CTRL_KEEP_ALIVE_TIME, self._ctrl_dead, [cid]),
                            "count": count}
        self._ctrls[cid]["timer"].start()
        self.logger.debug("Started/Restarted keep alive timer for controller %s" % cid)

    def _init_path_comp_timer(self):
        """ Start/Restart the path computation timer used to consilidate paths computation """
        if self._path_comp_timer is not None:
            self._path_comp_timer.cancel()

        self.logger.debug("Initiated path computation consolidation timer!")
        self._path_comp_timer = Timer(self.PATH_COMP_TIME, self._compute_inter_domain_paths)
        self._path_comp_timer.start()

    def _init_root_keep_alive_timer(self):
        """ Start/Restart the root keep alive send timer used to ensure that the send chanel
        is kept open.
        """
        if self._root_keep_alive_timer is not None:
            self._root_keep_alive_timer.cancel()

        self.logger.debug("Initiated the root keep alive timer")
        self._root_keep_alive_timer = Timer(self.ROOT_KEEP_ALIVE_TIME, self._send_root_keep_alive)
        self._root_keep_alive_timer.start()

    def _send_root_keep_alive(self):
        """ Send a message on `:cls:attr:(_chn_sned)` to keep the controller allive. Restart the
        keep alive timer once done by calling `_init_root_keep-alive_timer`.
        """
        self._safe_send("root.keep_alive", "ROOT_ID")
        self._init_root_keep_alive_timer()


    # ---------- Communication channel helper methods -----------


    def _safe_send(self, routing_key, data):
        """ Safely send data on the open RabbitMQ channel `:cls:attr:(__chn_send)` using the
        routing key `routing_key` and sending data `data`. Method is threadsafe and uses
        `:cls:attr:(__send_lock)`. If a exception is generated while sending the send channel
        is restartd and the send operation re-tried. If `data` is not a string it's pickeld
        before sending

        TODO: Implement a time-out to give up after several retires (maybe)?

        Args:
            routing_key (str): Routing key to use for sending data
            data (obj or str): Data to pickle and send
        """
        # If data is not a string pickle it
        if not isinstance(data, str):
            data = pickle.dumps(data)

        try:
            with self.__send_lock:
                self.__chn_send.basic_publish(exchange=self.EXCHANGE, routing_key=routing_key, body=data)
        except pika.exceptions.AMQPError:
            self.logger.error("Exception while sending, restarting and trying again")

            # Close the send channel and connection
            if self.__chn_send is not None and self.__chn_send.is_open:
                self._safe_cmd(self.__chn_send.close)
            if self.__con_send is not None and self.__con_send.is_open:
                self._safe_cmd(self.__con_send.close)

            # Restart the connection and channel and re-call the safe send command
            self.__con_send = pika.BlockingConnection(pika.ConnectionParameters(host=HOST))
            self.__chn_send = con_send.channel()
            self._safe_send(routing_key, data)

    def _safe_cmd(self, action):
        """ Execute a threadsafe RabbitMQ command catching any errors and supressing them.

        Args:
            action (method): Method to execute
        """
        try:
            action()
        except pika.exceptions.AMQPError:
            self.logger.info("Suppressed AMQPError exception")
            return


    # ---------- EXTRA HELPER METHODS ---------


    def _write_controller_state(self):
        """ Output the controller state to the predetermined output files. The controller state
        includes the topology as well as the paths computed and installed
        """
        with open("old_send.tmp", "w") as f:
            f.write(pprint.pformat(self._old_send, indent=2))
        with open("paths.tmp", "w") as f:
            f.write(pprint.pformat(self._old_paths, indent=2))
        with open("topo.tmp", "w") as f:
            f.write(pprint.pformat(self._topo, indent=2))
        with open("graph.tmp", "w") as f:
            f.write(pprint.pformat(self._graph.topo, indent=2))
        self.logger.info("Wrote controller state")


if __name__ == "__main__":
    # Initiate the logging module and the argument parser
    parser = ArgumentParser("Root SDN controller")
    parser.add_argument("--loglevel", type=str, default="info",
            help="Set the log level (debug, info, warning, error critical)")
    parser.add_argument("--log-file", type=str, default=None,
            help="Output log to standard output and write to a file")
    parser.add_argument("--te_candidate_sort_rev", required=False, type=str, default="true",
            help="TE sort paths in decending (true, default) or ascending order (false)")
    parser.add_argument("--te_partial_accept", required=False, type=str,
            default="false", help="TE accept partial solutions (default false)")
    args = parser.parse_args()

    loglevel = 20
    if args.loglevel == "debug":
        loglevel = 10
    elif args.loglevel == "info":
        loglevel = 20
    elif args.loglevel == "warning":
        loglevel = 30
    elif args.loglevel == "error":
        loglevel = 40
    elif args.loglevel == "critical":
        loglevel = 50
    elif args.loglevel.isdigit():
        loglevel = int(args.loglevel)

    # Convert the string flags to booleans (strict parse based on default)
    args.te_candidate_sort_rev = False if (args.te_candidate_sort_rev.lower() == "false") else True
    args.te_partial_accept = True if (args.te_partial_accept.lower() == "true") else False

    logging.basicConfig(format="[%(levelname)1.1s] %(funcName)-20.20s : %(message)s")
    logger = logging.getLogger("RootCtrl")
    logger.setLevel(loglevel)

    if args.log_file is not None:
        handler = logging.handlers.WatchedFileHandler(args.log_file)
        format = logging.Formatter(fmt="[%(levelname)1.1s] %(funcName)-20.20s : %(message)s")
        handler.setFormatter(format)
        logger.addHandler(handler)

    root = RootCtrl(logger, args.te_candidate_sort_rev, args.te_partial_accept)
    try:
        root.start()
    except KeyboardInterrupt:
        # Catch any keyboard interupts to allow gracefull exit
        pass
    except Exception as ex:
        logger.critical("Exception occured: %s" % ex)
        logger.critical("%s" % traceback.format_exc())
    finally:
        # Close the RabbitMQ connections and cancel any keep alive timers
        logger.info("Cleaning up connections to RabbitMQ")
        root.stop()
