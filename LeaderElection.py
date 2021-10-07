#!/usr/bin/python

from threading import Thread, Lock, Event, Timer
import pika
import pickle
import random
import time


class LeaderElection:
    """ Class that handles leader election between a group of instances. The
    master instance is selected based on ID order were lowest inst_id promotes
    itself to master. All instances advertise their inst_id and role in regular
    keep-alive messages. Module does not use role change notifications or a
    re-negotation phase on master failure. The leader election process will,
    once the master instance has failed, check if the local instance needs to
    promote itself to the new master (i.e. it's inst_id is lower than the other
    active instances). This approach reduces the number of inter-instance
    mesages and dependency on other devices (local instance knows if it needs
    to become the new master).

    Generate execution:
        1) On start of the module, instance has no role. A find request is
        generated and sent to all instances in the current domain to allow
        sync of keep-alive timers. A init timer is stated which waits a
        defined amount of time before assigning role to local instance (i.e
        should we become a master or slave).

        2) Generate and send periodic keep-alives messages. On keep-alive timer
        trigger, start the time-out detect timer.

        3) On time-out detect timer trigger, go through all controllers and
        decrement observed keep alive count. If value reaches 0, expire
        instance. If failed instance is master, check if we are new master.

        4) On keep-alive receive, increemnt controller keep alive count.

    The controller failure detection works similar to a token bucket were
    a token (count) is added for every received keep-alive and every
    time-out interval, a count is removed. This offers a tolerance of several
    keep-alive intervals for controller failures (in case delays occur).
    """

    HOST = "127.0.0.1"
    EXCHANGE = "SDN_Bridge"
    EXCHANGE_TYPE = "topic"

    # Timer interval values
    KEEP_ALIVE_INTERVAL = 1.0
    # XXX: Timeout timer is reset every keep alive interval
    TIMEOUT_INTERVAL = KEEP_ALIVE_INTERVAL / 2.0

    # XXX: Set the init period to the keep alive timeout interval (for every
    # keep alive period wait n seconds before timeing out controllers to
    # account for latency on the controll channel). When the instance starts,
    # a role request is sent out so the local instance should discovery other
    # active instances almost instantly (accounting for some latency).
    INIT_TIMER_INTERVAL = TIMEOUT_INTERVAL

    # Wait N missed keep-alive intervals before declaring a controller as
    # failed (set the controller keep-alive counter to this value when a keep
    # alive is received).
    KEEP_ALIVE_WAIT_MISS = 1

    def __init__(self, logger, dom_id=0, channel_format="c.{DOM_ID}.discover",
                    inst_id=None):
        """ Initiate a new leader election instance on a seperate therad.

        Args:
            logger (obj): Logger instance to use for message output
            app (RyuApp): Instance of the controller to notify of role change
            dom_id (int): ID of the domain the controller instance is in
            channel_format (str): Name of the channel used to communicate with
                other instances in the same domain.
            inst_id (int): Controller instance ID. Used to identify a instance.
                If set to null (default) a random inst_id is generated.
        """
        # Save the loger and generate the channel to bind
        self.logger = logger
        self.channel = channel_format.format(DOM_ID=dom_id)

        # Define empty variables to hold the send and receive connections and channels
        self.con_send = None
        self.con_recv = None
        self.chn_send = None
        self.chn_recv = None
        self.queue_name = None

        # Generate a random inst_id if one was not provided and initiate the
        # role attributes, locks, timers and dictionaries
        if inst_id is None:
            self._regenerate_inst_id()
        else:
            self.inst_id = inst_id

        self.ctrl_role = "unknown"
        self.ctrl_role_lock = Lock()
        self.ctrl_role_change_event = Event()

        self.keep_alive_timer = None
        self.timeout_timer = None
        self.init_timer = None
        self.send_lock = Lock()
        self.controllers = {}

        # Construct and start the main thread
        self.thread = Thread(target=self._main_loop, name="LeaderElectionTH")
        self.thread.start()

    def get_ctrl_role(self):
        """ Return the controller role """
        with self.ctrl_role_lock:
            return self.ctrl_role

    def set_ctrl_role(self, role):
        """ Set the controller role """
        with self.ctrl_role_lock:
            self.ctrl_role = role
            self.logger.info("Set controller role to %s" % role)
            self.logger.critical("XXXEMUL,%f,role,%s" % (time.time(), role))
            self.ctrl_role_change_event.set()

    def master_exists(self):
        """ Check if the controller list already contains a master controller.
        Note, this method dosen't consider the counter, only if a master role
        instance exists in the controller dictionary. If the master is in the
        process of failing, the current instance will be set to slave and will
        perform the appropriate switch-over once the master has failed.

        Returns:
            bool: True if a master already exists, false otherwise
        """
        for inst_id,data in self.controllers.items():
            if data["role"] == "master":
                return True
        return False


    def stop(self):
        """ Stop the thread by stopping the receive channel from consuming. Method
        blocks until the thread object finishes """
        self.con_recv.add_callback_threadsafe(
            self.chn_recv.stop_consuming
        )

        # Wait for the thread to stop and null the instance
        self.thread.join()
        self.thread = None

    def is_active(self):
        """ Check if the worker thread is active (not null).

        Returns:
            bool: True if active, false otherwise
        """
        return self.thread is not None

    def _regenerate_inst_id(self):
        """ Regenerate the controller's instance ID """
        self.logger.info("Regenerating inst_id")
        self.inst_id = random.randint(1,10000)

    def is_init_phase(self):
        """ Check if controller is currently in the initiation phase,
        `:cls:attr:(init_timer)` is not null.

        Returns:
            bool: True if instance is in init phase, false otherwise
        """
        return self.init_timer is not None


    # ---------------------- TIMER METHODS ----------------------


    def _reset_keep_alive_timer(self):
        """ Reset the keep alive timer, advertise the controller inst_id and
        reset the time-out timer to detect failed instnaces.
        """
        # If the timer is running cancel it
        if self.keep_alive_timer is not None:
            self.keep_alive_timer.cancel()

        # Send the inst_id and resetart the timer
        self._send_inst_id()
        self.keep_alive_timer = Timer(self.KEEP_ALIVE_INTERVAL, self._keep_alive_timer_work)
        self.keep_alive_timer.start()
        self._reset_timeout_timer()

    def _keep_alive_timer_work(self):
        """ Callback executed on keep alive timer trigger """
        self.keep_alive_timer = None
        self._reset_keep_alive_timer()

    def _reset_timeout_timer(self):
        """ Reset the time-out timer """
        # If the timer is running cancel it
        if self.timeout_timer is not None:
            self.timeout_timer.cancel()

        self.timeout_timer = Timer(self.TIMEOUT_INTERVAL, self._timeout_timer_work)
        self.timeout_timer.start()

    def _timeout_timer_work(self):
        """ Callback executed on timeout timer trigger. Check if a controller
        has failed. If the master controller has failed, perform leader
        selection (promote myself to master if inst_id is lowest)
        """
        # Check for dead instances and if we need to become the new master
        check_master = False
        for inst_id,data in self.controllers.items():
            # OUTPUT THE CURRENT INSTANCE ID COUNT
            self.logger.info("Inst %d count %s %f" % (inst_id, data["count"],
                                                        time.time()))

            if data["count"] <= 0:
                # Found a dead instance
                self.logger.info("\tInst %d timed out (%s)" % (inst_id, data))
                self.logger.critical("XXXEMUL,%f,inst_fail,%s" % (time.time(),
                                                                inst_id))
                if data["role"] == "master":
                    check_master = True

                # Delete the dead instance from the list
                self.logger.info("\tInst %d count %s" % (inst_id, data["count"]))
                del self.controllers[inst_id]
            else:
                # Consume a received keep alive for the controller
                data["count"] -= 1

        ctrl_keys = sorted(self.controllers.keys())
        if (check_master and (len(ctrl_keys) == 0 or
                    self.inst_id <= ctrl_keys[0])):
            # XXX: We are the new master, take over
            self.set_ctrl_role("master")

        # Clear the timer
        self.timeout_timer = None

    def _init_timer_work(self):
        """ Callback executed on initiation timmer trigger (start of app). """
        self.logger.info("Initiation timmer triggered")
        self.init_timer = None

        # Work out if we should become the new mater os a slave. We will be set
        # as master only if there are no other instances, or other non-master
        # instances exist and our inst_id is the lower number.
        ctrl_keys = sorted(self.controllers.keys())
        if (len(ctrl_keys) == 0 or (self.master_exists() == False and
                                    self.inst_id <= ctrl_keys[0])):
            self.set_ctrl_role("master")
        else:
            self.set_ctrl_role("slave")


    # -------------------- RabbitMQ Operation Methods ---------------------


    def _send_inst_id(self):
        """ Send the controller's inst_id and role """
        obj = {"msg": "keep_alive",
                "inst_id": self.inst_id,
                "role": self.get_ctrl_role(),
                "QID": self.queue_name}
        obj_str = pickle.dumps(obj)
        self._pika_safe_send(self.channel, obj_str)
#        self.logger.info("Sent keep alive %s (QID: %s) at %f" % (self.inst_id,
#                            self.queue_name, time.time()))


    def _send_find(self):
        """ Send a find message """
        obj = {"msg": "find"}
        obj_str = pickle.dumps(obj)
        self._pika_safe_send(self.channel, obj_str)
        self.logger.info("Sending find")
        self.logger.critical("XXXEMUL,%f,send_find" % time.time())

        # Start the init timer work to promote to master if no ctrl responds
        self.init_timer = Timer(self.INIT_TIMER_INTERVAL, self._init_timer_work)
        self.init_timer.start()


    def _on_receive(self, chn, method, properties, body):
        """ Process the received message """
        data = pickle.loads(body)

        if data["msg"] == "find":
            # Received a controller find request so reset the timers
            self._reset_keep_alive_timer()
            #self._reset_timeout_timer()

        elif data["msg"] == "keep_alive":
            # Received a keep alive message, if this message is from the
            # current instance just ignore it
            if data["QID"] == self.queue_name:
                return

            self.logger.info("Got keep alive: %s" % data)

            # Check for inst_id collisions
            if data["inst_id"] == self.inst_id:
                if self.get_ctrl_role() == "unknown":
                    # If there is a collision and we don't have a role regen
                    # the inst_id
                    self._regenerate_inst_id()
                else:
                    if data["role"] == "master":
                        # If other end is a master, regenerate local inst_id
                        # TODO: What happens if there are two masters with a
                        # colided inst_id? Is this even a thing that needs to
                        # be considered?
                        self._regenerate_inst_id()
                    elif data["role"] == "slave" and self.get_ctrl_role() == "slave":
                        if data["QID"] < self.queue_name:
                            # Both ctrls are slave so regen if the queue name is lower
                            self._regenerate_inst_id()
                return
            elif data["inst_id"] not in self.controllers:
                # Discovered a new instance, add details
                self.controllers[data["inst_id"]] = {
                    "role": "unknown",
                    "count": 0
                }

            # Update instance info with advertised role and increment count
            self.controllers[data["inst_id"]]["role"] = data["role"]
            self.controllers[data["inst_id"]]["count"] = self.KEEP_ALIVE_WAIT_MISS

            # If local instance is in init phase, and a master instance was
            # discovered, demote instance to slave and end init phase early.
            if self.is_init_phase() and data["role"] == "master":
                self.logger.info("Found master, stopping init phase early")
                self.set_ctrl_role("slave")
                self.init_timer.cancel()
                self.init_timer = None

            # XXX: While the above code makes sense, the SW would take some
            # time to establish a connection with the controller via the topo
            # discovery module (OFPStateChange). Even if a early role change is
            # triggered it may take some time from sending a role change to the
            # switches.
        else:
            # unknown operation
            self.logger.info("Unknown operation received by leader election module")


    # -------------------- Main Thread Worker Method ----------------------


    def _main_loop(self):
        """ Main thread loop, init two pika sockets and block on receive """
        try:
            # Initiate two rabbitMQ connections, one for sending and one for reciving
            self.con_send, self.chn_send = self._init_rabbitmq_con()
            self.con_recv, self.chn_recv = self._init_rabbitmq_con()

            # Register for messages on the sending connection
            res = self.chn_recv.queue_declare("", exclusive=True)
            self.queue_name = res.method.queue
            self.chn_recv.queue_bind(exchange=self.EXCHANGE, queue=self.queue_name, routing_key=self.channel)

            # Initiate the timers
            self._reset_keep_alive_timer()
            #self._reset_timeout_timer()
            self.logger.info("Initiated controller RabbitMQ connections, chanel and exchanges")

            # Send a controller find message
            self._send_find()

            self.chn_recv.basic_consume(queue=self.queue_name, on_message_callback=self._on_receive,
                                        auto_ack=True)
            self.chn_recv.start_consuming()
        finally:
            self.logger.info("Cleaning up leader election connections to RabbitMQ")

            # Stop any running timers
            if self.keep_alive_timer is not None:
                self.keep_alive_timer.cancel()
            if self.timeout_timer is not None:
                self.timeout_timer.cancel()

            # Consolidate closing connections (catch any RabbitMQ errors)
            if self.chn_recv is not None and self.chn_recv.is_open:
                self._pika_safe_cmd(self.chn_recv.close)
            if self.chn_send is not None and self.chn_send.is_open:
                self._pika_safe_cmd(self.chn_send.close)
            if self.con_recv is not None and self.con_recv.is_open:
                self._pika_safe_cmd(self.con_recv.close)
            if self.con_send is not None and self.con_send.is_open:
                self._pika_safe_cmd(self.con_send.close)


    # -------------------- RabbitMQ initiation and helper methods ----------------------


    def _init_rabbitmq_con(self):
        """ Initiate a new RabbitMQ connection and retrieve the connection objects.

        Returns:
            (obj, obj): Connection object and chanel for the connection
        """
        con = pika.BlockingConnection(pika.ConnectionParameters(host=self.HOST))
        chn = con.channel()
        chn.exchange_declare(exchange=self.EXCHANGE, exchange_type=self.EXCHANGE_TYPE, auto_delete=True)
        return con, chn


    def _pika_safe_send(self, routing_key, data):
        """ Perform a thread safe send command on `:mod:attr:(chn_send)` using the routing
        key `routing_key` and sending string `data`. Method will try to aquire lock
        `:mod:attr:(send_lock)` before sending data. If a Pike exception occurs when
        sending the method will try to re-start the chanel instance and re-call the
        send method.

        Args:
            routing_key (str): Routing key to use for sending data
            data (str): Data to send
        """
        try:
            with self.send_lock:
                self.chn_send.basic_publish(exchange=self.EXCHANGE, routing_key=routing_key, body=data)
        except pika.exceptions.AMQPError:
            self.logger.error("Exception while sending, restarting and trying again")

            # Close the send channel and connection
            if self.chn_send is not None and self.chn_send.is_open:
                self._pika_safe_cmd(chn_send.close)
            if self.con_send is not None and self.con_send.is_open:
                self._pika_safe_cmd(con_send.close)

            # Restart the connection and channel and re-call the safe send command
            self.con_send = pika.BlockingConnection(pika.ConnectionParameters(host=self.HOST))
            self.chn_send = con_send.channel()
            self.pika_safe_send(routing_key, data)


    def _pika_safe_cmd(self, action):
        """ Perform a safe Pika command by catching any exceptions and supressing them.

        Args:
            action (method): Method to execute
        """
        try:
            action()
        except pika.exceptions.AMQPError:
            self.logger.info("Suppressed AMQPError exception")
            return
