#!/usr/bin/python

""" Local controller inter-controller communication that sends information to the
other controllers and allows inter-controller communications.
"""

from ryu.lib import hub
import pika
import pickle
import random
from threading import Timer, Lock


# --- Module to perform local leader election
from LeaderElection import LeaderElection


class ControllerCommunication:
    """ Communication class that connects to RabbitMQ exchanging messages.

    Attr (Static):
        HOST (str): Address of the RabbitMQ server
        EXCHANGE (str): Name of the exchange to use
        EXCHANGE_TYPE (str): Type of the exchange (direct)
        KEEP_ALIVE (int): Number of seconds of inactivity to trigger ctrl
            keep alive (send controller ID).
        *_RK (str): Routing keys used to send information

    Attr:
        logger (obj): Logger instance used to output debug information
        app (obj): Controller instance that initiated the inter controller communication obj
        thread (ryu.lib.hub): Greenleat object instance (thread)
        con_send (obj): RabbitMQ send connection instance
        con_recv (obj): RabbitMQ receive connection instance
        chn_send (obj): RabbitMQ send channel instance
        chn_recv (obj): rabbitMQ recieve channel instance
        cid (int): ID of the controller
        send_lock (threading.Lock): Send channel lock used to make operation thread safe
        inter_dom_paths (dict): Old path computation request received from the root
            controller to install inter-domain paths.
        leader_elect (obj): Instance to the leader election module
        leader_elect_worker (ryu.lib.hub): Leader election role change worker thread
    """


    HOST = "127.0.0.1"
    EXCHANGE = "SDN_Bridge"
    EXCHANGE_TYPE = "topic"
    KEEP_ALIVE = 4

    # --- Routing keys used to send comments using RabbitMq ---

    # Controller discovery and keep alive (periodically send CID)
    DISCOVER_RK = "root.c.discover"
    # Send topology of local controller to root controller
    TOPO_RK = "root.c.topo"
    # Request the CID of an unknown switch that was detected via LLDP packets
    UNKNOWN_SW_RK = "root.c.inter_domain.unknown_sw"
    # Notify the root controlelr tha an inter-domain port is down
    DEAD_PORT_RK = "root.c.inter_domain.dead_port"
    # Inform the root controller of the traffic on a inter-domain link
    INTER_LINK_TRAFFIC_RK = "root.c.inter_domain.link_traffic"
    # Inform the root controller of congestion on a inter-domain link
    INTER_LINK_CONGESTION_RK = "root.c.inter_domain.congestion"
    # Inform the root controller that a egress changed for a inter-domain link
    INTER_LINK_EGRESS_CHANGE_RK = "root.c.inter_domain.egress_change"
    # Inform the root controller that a ingress changed for a inter-domain link
    INTER_LINK_INGRESS_CHANGE_RK = "root.c.inter_domain.ingress_change"

    # ----------------------------------------------------------


    def __init__(self, logger, app, dom_id=1):
        """ Intiate a new controller com instance and bind the app and loger objects

        Args:
            logger (obj): Logger instance to use when outputing debug info
            app (RyuApp): Instance of the controller to retrieve topology and notify of
                events.
        """
        self.thread = None
        self.logger = logger

        self.con_send = None
        self.con_recv = None
        self.chn_send = None
        self.chn_recv = None

        self.app = app
        self.keep_alive_timer = None

        self.leader_elect_worker = None
        self.leader_elect = None

        # Save the provided domain_id
        # TODO: FIXME, maybe add a d or something to it. Issues appear when the CID is the same
        # as a switch on the root controller.
        self.cid = int("100%d" % dom_id)

        # Initiate the send lock and the inter domain path instructions dictionary
        self.send_lock = Lock()
        self.inter_dom_paths = {}


    # -------------- THREAD METHODS -------------


    def start(self, inst_id=None):
        """ Initiate the inter controller communication as a new GreenThread and configure
        the exit handler to close the RabbitMQ connections.

        Args:
            inst_id (int): ID of local instance to pass to leader election
                module. Defaults to None (generate random inst_id).
        """
        self.thread = hub.spawn(self)
        self.thread.name = 'ControllerCommunication'
        self.thread.link(self._cleanup_connection)

        # Initiate the leader election thread and modules
        self.leader_elect = LeaderElection(self.logger, self.cid,
                                            inst_id=inst_id)
        self.leader_elect_worker = hub.spawn(self.role_change_work)
        self.leader_elect_worker.name = "LeaderElectionWorker"


    def stop(self):
        """ Stop the threads and cancel any keep alive timers. """
        # Stop the keep alive timer
        self.stop_keep_alive_timer()

        if self.is_active():
            # Stop the leader election instance
            self.leader_elect.stop()

            # Kill the hub threads
            hub.kill(self.thread)
            hub.kill(self.leader_elect_worker)
            hub.joinall([self.thread, self.leader_elect_worker])
            self.thread = None
            self.leader_elect_thread = None


    def __call__(self):
        """ Thread worker method. Initiate two RabbitMQ connections, one for sending and
        one for reciving. Consume messages from the communication chanell and bind handler
        for recived messages.
        """
        # Initiate two rabbitMQ connections, one for sending and one for reciving
        self.con_send, self.chn_send = self._init_rabbitmq_con()
        self.con_recv, self.chn_recv = self._init_rabbitmq_con()

        # Register for messages on the sending connection
        res = self.chn_recv.queue_declare("", exclusive=True)
        queue_name = res.method.queue
        self.logger.info("CID:%d" % self.cid)
        self.chn_recv.queue_bind(exchange=self.EXCHANGE, queue=queue_name, routing_key="c.%d" % self.cid)
        self.chn_recv.queue_bind(exchange=self.EXCHANGE, queue=queue_name, routing_key="c.all")

        # Start reciving inter-ctrl messages
        self.logger.info("Initiated controller RabbitMQ connections, chanel and exchanges")
        self.chn_recv.basic_consume(queue=queue_name, on_message_callback=self.on_receive, auto_ack=True)
        self.chn_recv.start_consuming()


    def is_active(self):
        """ Is the inter-communication object active and connected.

        Returns:
            bool: True if the thread is active (object exists), false otherwise.
        """
        return self.thread is not None


    def role_change_work(self):
        """ Worker method that checks for role change events. On a role change
        (```ctrl_role_change_event``` from `:cls:attr:(leader_elect)` set)
        call the app promote/demote role method (`:cls:attr:(app)`). If the
        role is 'master', send an early domain keep alive to prevent the root
        from timing out the area due to instance failures.
        """
        while self.leader_elect.is_active():
            self.leader_elect.ctrl_role_change_event.wait(1)
            if self.leader_elect.ctrl_role_change_event.is_set():
                self.leader_elect.ctrl_role_change_event.clear()

                # Get the ctrl role and update it
                role = self.get_ctrl_role()
                self.logger.info("Received controller role %s" % role)
                if role == "slave":
                    self.app.demote_slave()

                    # Stop the keep alive timer as we are a slave instance
                    self.stop_keep_alive_timer()
                elif role == "master":
                    self.app.promote_master()

                    # Send a keep-alive for the domain as we are the new
                    self.send_cid()


    # ------------ CONTROLLER ROLE HELPER METHDOS -----------


    def get_ctrl_role(self):
        """ Return the current controller role as a string.

        Returns:
            str: Controller role, either master or slave.
        """
        return self.leader_elect.get_ctrl_role()


    def is_master(self):
        """ Return if the current controller is the master of the domain.

        Returns:
            bool: True if it is, false otherwise.
        """
        return self.get_ctrl_role() == "master"


    def is_slave(self):
        """ Return if the current controller is a slave of the domain.

        Returns:
            bool: True if it is, false otherwise.
        """
        return self.get_ctrl_role() == "slave"


    # ----------- HELPER METHODS ------------


    def _init_rabbitmq_con(self):
        """ Initiate a new RabbitMQ connection and retrieve the connection objects.

        Returns:
            (obj, obj): Connection object and chanel for the connection
        """
        con = pika.BlockingConnection(pika.ConnectionParameters(host=self.HOST))
        chn = con.channel()
        chn.exchange_declare(exchange=self.EXCHANGE, exchange_type=self.EXCHANGE_TYPE, auto_delete=True)
        return con, chn


    def _cleanup_connection(self, args):
        """ Close the RabbitMQ connection elements and channels. This method is automatically
        called on kill of the GreenThread `self.thread`.
        """
        self.logger.info("Closing RabbitMQ chanel and connection")

        if self.chn_send is not None:
            self.chn_send.close()
        if self.chn_recv is not None:
            self.chn_recv.close()

        if self.con_send is not None:
            self.con_send.close()
        if self.con_recv is not None:
            self.con_recv.close()


    def pika_safe_send(self, routing_key, data):
        """ perform a thread safe send command on `:cls:attr:(chn_send)` using the routing key
        `routing_key` and sending string `data`. Method will try to aquire a lock `:cls:attr:(send_lock)`
        before sending data. If a pika exception occurs when sending, the method will try to re-start the
        chanel instance and re-call the send method.

        Args:
            routing_key (str): Routing key to use for sending data
            data (str): Data to send
        """
        if not self.is_master():
            self.logger.debug("Stopping message as we are not master (%s)" % routing_key)
            return

        try:
            with self.send_lock:
                self.chn_send.basic_publish(exchange=self.EXCHANGE, routing_key=routing_key, body=data)
        except pika.exceptions.AMQPError:
            self.logger.error("---Exception while sending message, restartin chanel and trying again")

            # Restart the send channel and connection
            if self.chn_send is not None and self.chn_send.is_open:
                self.chn_send.close()
            if self.con_send is not None and self.con_send.is_open:
                self.con_send.close()

            self.con_send, self.chn_send = self._init_rabbitmq_con()
            self.pika_safe_send(routing_key, data)


    def _update_inter_dom_paths(self, hkey, paths):
        """ Update the inter domain paths dictionary with a new path. Method adds, removes or
        replaces paths in `:cls:attr:(inter_dom_paths)`, depending on the action of `paths` and
        weather or not the path already exists.

        Args:
            hkey (tuple): Source destination path pair key
            paths (dict): Path instruction received from the root controller
        """
        if paths[0]["action"] == "delete":
            if hkey in self.inter_dom_paths:
                del self.inter_dom_paths[hkey]
        elif paths[0]["action"] == "add":
            self.inter_dom_paths[hkey] = paths
        else:
            self.logger.info("Unknown action for path %s. Can't update inter dom paths dict" % paths)



    # ------------ SEND AND RECEIVE HANDLERS AND METHODS ------------


    def on_receive(self, chn, method, properties, body):
        """ On recive, process the message and perform the operation specified by key 'msg' """
        data = pickle.loads(body)

        if data["msg"] == "get_topo":
            # Recieved a topology request, send the topology information to the root controller
            self.logger.info("Resending host information")
            self.send_topo(inter_dom_paths=True)

        elif data["msg"] == "get_id":
            # Recieved a CID request, send the CID to the root controller
            self.logger.info("Resending controller ID")
            self.send_cid()

        elif data["msg"] == "unknown_sw":
            # Process a unknown Switch CID response message to associate a unknown link with
            # a external domain
            self.logger.info("Found CID resolve")
            key = (data["sw"], data["port"], data["dest_sw"])
            self.app.unknown_links[key] = data["cid"]
            self.logger.info("New unknown links: %s" % self.app.unknown_links)

        elif data["msg"] == "compute_paths":
            # Received inter-domain path computation request
            self.logger.info("Compute path received")
            for hkey,paths in data["paths"].iteritems():
                self.logger.info("%s: %s" % (hkey, paths))
                self.app.compute_path_segment(hkey, paths)
                self._update_inter_dom_paths(hkey, paths)

        elif data["msg"] == "ctrl_dead":
            # Recieved notifcation that a controller is no longer connected
            self.logger.info("Recieved controller dead notification")

            # Find the links that resolve to the dead controller CID and remove them
            remove = []
            for lk, lcid in self.app.unknown_links.iteritems():
                if lcid == data["cid"]:
                    remove.append(lk)
            for r in remove:
                del self.app.unknown_links[r]

            self.logger.info("New unknown links: %s" % self.app.unknown_links)

        elif data["msg"] == "processed_con":
            # Received processed inter-domain congestion message
            self.logger.info("Received processed inter-domain congestion for sw %s port %s" %
                                (data["sw"], data["port"]))
            key = (data["sw"], data["port"])
            if key in self.app.TE.inter_domain_over_util:
                del self.app.TE.inter_domain_over_util[key]
                self.logger.info("Congestion resolved, removed from outstanding request dict")

        else:
            # Unknown operation ...
            self.logger.info("Unknown operation recived ... ignoring!")


    def send_cid(self):
        """ Send the controller ID and other attributes to the root controller. Method allows
        discovery of controlers (opened channels).
        """
        # Do not send CID if module not active or instance is not master
        if self.is_active() == False:
            return
        if self.is_master() == False:
            return

        obj = {"cid": self.cid, "te_thresh": self.app.TE.util_thresh}
        obj_str = pickle.dumps(obj)
        self.pika_safe_send(self.DISCOVER_RK, obj_str)

        # Clear the keep alive timer (we sent data)
        self.clear_keep_alive_timer()


    def send_topo(self, inter_dom_paths=False):
        """ Send the local controller information to the other subscribed controllers. The
        inter-domain links, connected hosts, switches, other domain config attributes, as
        well as the old inter-domain path computation requests are sent.

        Args:
            inter_dom_paths (bool): Should we send the old inter-domain path instructions.
                Defaults to False (do not send)
        """
        if self.is_active() == False:
            return

        hosts = self.app.hosts
        # Generate the set of switches from the topology
        # TODO: This needs to be optimised as well, don't really like re-doing this iteration
        # for every topo change !!!
        switches = self.app.graph.get_switches()

        # Retrieve the eth and ip address of the host (for egress instalation)
        host_info = []
        for h in hosts:
            info = self.app.graph.get_port_info(h, -1)
            host_info.append((h, info["eth_address"], info["address"]))

        # Add the speed of the ports to the unknown links GID
        ulink = {}
        for ulk, uldata in self.app.unknown_links.iteritems():
            speed = 0
            pinfo = self.app.graph.get_port_info(ulk[0], ulk[1])
            if pinfo is not None:
                speed = pinfo["speed"]
            ulink[(ulk[0], ulk[1], ulk[2], speed)] = uldata

        obj = {"cid": self.cid, "hosts": host_info, "switches": switches, "unknown_links": ulink,
                "te_thresh": self.app.TE.util_thresh}

        if inter_dom_paths:
            obj["paths"] = self.inter_dom_paths

        obj_str = pickle.dumps(obj)
        self.pika_safe_send(self.TOPO_RK, obj_str)

        # Clear the keep alive timer (we sent data)
        self.clear_keep_alive_timer()


    def notify_outside_link(self, sw, port, dest_sw, speed):
        """ Notify the controller of links that do not belog to the current switch
        instance.

        Args:
            sw (int): DPID of local switch that recived LLDP message
            port (int): prt where LLDP packet was recived on `sw`.
            dest_sw (int): unknown switch DPID (in LLDP message)
            speed (int): Capacity of port in bits
        """
        if self.is_active() == False:
            return

        obj = {"cid": self.cid, "sw": sw, "port": port, "dest_sw": dest_sw, "speed": speed}
        obj_str = pickle.dumps(obj)
        self.pika_safe_send(self.UNKNOWN_SW_RK, obj_str)

        # Clear the keep alive timer (we sent data)
        self.clear_keep_alive_timer()
        self.logger.info("Notified controller of outside links")


    def notify_inter_domain_port_down(self, link_key):
        """ Notify the root controller that a inter-domain link's port went down.

        Args:
            link_key (triple): unknown link key entry of the port that wen't down
        """
        if self.is_active() == False:
            return

        # Get the external domain ID and remove the link isntance
        cid = self.app.unknown_links[link_key]
        if isinstance(cid, list):
            cid = None
        del self.app.unknown_links[link_key]
        print(self.app.unknown_links)

        # Send the notification to the root controller
        obj = {"cid": self.cid, "sw": link_key[0], "port": link_key[1], "to_cid": cid}
        obj_str = pickle.dumps(obj)
        self.pika_safe_send(self.DEAD_PORT_RK, obj_str)


    def notify_inter_domain_link_traffic(self, sw, port, tx_bps):
        """ Tell the root controller the ammount of traffic recorded on an inter-domain link.

        Args:
            sw (int): DPID of the switch that has the inter-domain port
            port (int): Port on `sw` of the inter-domain link
            rate (double): Usage on the inter-domain link
        """
        if self.is_active() == False:
            return

        obj = {"cid": self.cid, "sw": sw, "port": port, "traff_bps": tx_bps}
        obj_str = pickle.dumps(obj)
        self.pika_safe_send(self.INTER_LINK_TRAFFIC_RK, obj_str)


    def notify_inter_domain_congestion(self, sw, port, traff_bps, paths):
        """ Tell the root controller that we have congestion on an
        inter-domain link.

        Args:
            sw (int): DPID of the switch where the congestion links is
            port (int): Port of the congestion link
            traff_bps (float): Traffic in bps on congested link (based
                on source-destination pairs).
            paths (list of tupple): List of paths that are using the link
        """
        if self.is_active() == False:
            return

        obj = {
            "cid": self.cid, "sw": sw, "port": port,
            "traff_bps": traff_bps, "paths": paths,
            "te_thresh": self.app.TE.util_thresh
        }
        obj_str = pickle.dumps(obj)
        self.pika_safe_send(self.INTER_LINK_CONGESTION_RK, obj_str)


    def notify_egress_change(self, hkey, new_egress):
        """ A inter-domain TE optimisation occured which resulted in a egress change.
        Find and modify the egress of the received root controlelr paths in
        `:cls:attr:(inter_dom_paths)` and notify the root controller of the egress change.

        Args:
            hkey (tuple): Source destination pair key of path that was modified
            new_egress (tuple): New egress switch details (sw, port)
        """
        if self.is_active() == False:
            return

        # Get the egress modification
        paths = None
        if hkey in self.inter_dom_paths:
            paths = self.inter_dom_paths[hkey]
            prim = paths[0]
            sec = None

            # Iterate through the installed paths and try to find the new egress
            for p in paths:
                if p["out"] == new_egress:
                    sec = p
                    break

            # If we found the correct out swap the primary paths with the secondary path
            # for which the egress belongs
            if sec is not None:
                old_egress = prim["out"]
                prim["out"] = new_egress
                sec["out"] = old_egress
                self.logger.info("Found the old root controller paths, modifying egress")
            else:
                self.logger.error("Could not find new egress in old root controller paths")
                return
        else:
            self.logger.error("Could not find hkey in old root controller paths to change egress")
            return

        # Notify the root controller of the egress change for the inter-domain path
        self.logger.info("Notifying the root controller of the egress change on the inter-domain path")
        obj = {"cid": self.cid, "hkey": hkey, "new_paths": paths}
        obj_str = pickle.dumps(obj)
        self.pika_safe_send(self.INTER_LINK_EGRESS_CHANGE_RK, obj_str)


    def notify_ingress_change(self, hkey, old_ingress, new_ingress, old_egress, new_egress):
        """ A inter-domain TE optimisation occured in a previous domain that caused the ingress
        of a inter domain path to change. Find and modify the ingress of the received root controller
        path in `:cls:attr:(inter_dom_paths)` and notify the root of the ingress change.

        Args:
            hkey (tuple): Source destination pair key of path that was modified
            old_ingress (tupple): Old ingress details
            new_ingress (tupple): New ingress details
            old_egress (tupple): Old egress details
            new_egress (tupple): New egress details
        """
        if self.is_active() == False:
            return

        paths = None
        if hkey in self.inter_dom_paths:
            paths = self.inter_dom_paths[hkey]
            prim = paths[0]
            sec = None

            # Look for the secondary path in the inter-dom installed paths list
            for p in paths:
                if p["in"] == new_ingress:
                    sec = p
                    break

            # If we found the correct paths swap the primary and secondary path ingress
            if sec is not None:
                prim["in"] = new_ingress
                sec["in"] = old_ingress
                self.logger.info("Found the old root controller paths, modifying ingress")

                # Only update egress if we are a transit inter-domain path segment and
                # if the new egress differs from the old one (try to preserve ports).
                if isinstance(old_egress, tuple) and not old_egress == new_egress:
                    prim["out"] = new_egress
                    sec["out"] = old_egress
                    self.logger.info("Modified egress of old root controller path")
            else:
                self.logger.error("Could not find new ingress in old root controller paths")
                return
        else:
            self.logger.error("Could not find hkey in old root controller paths to change ingress")
            return

        # Notify the root controller of the ingress change for the inter-domain path
        self.logger.info("Notifying the root controller of the ingress change on the inter-domain path")
        obj = {"cid": self.cid, "hkey": hkey, "new_paths": paths}
        obj_str = pickle.dumps(obj)
        self.pika_safe_send(self.INTER_LINK_INGRESS_CHANGE_RK, obj_str)



    # ---------- CONTROLLER KEEP ALIVE TIMER -----------


    def stop_keep_alive_timer(self):
        """ Stop any running instance of the keep-alive timer. Method should
        be called when instance is demoted to slave.
        """
        self.logger.debug("Stopping keep alive timer ...")
        if self.keep_alive_timer is not None:
            self.keep_alive_timer.cancel()
        self.keep_alive_timer = None


    def clear_keep_alive_timer(self):
        """ Start/reset the inactivity keep alive timer for the controller.
        The timer will trigger a method that sends the controller ID to the
        root controller every `cls:CTRL_KEEP_ALIVE` of inactivity (no messages
        sent) to prevent the connection from closing.
        """
        if self.keep_alive_timer is not None:
            self.keep_alive_timer.cancel()

        self.keep_alive_timer = Timer(self.KEEP_ALIVE, self.send_cid)
        self.keep_alive_timer.start()
        self.logger.debug("Cleared controller keep alive timer")
