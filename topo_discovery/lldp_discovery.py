# Copyright (C) 2013 Nippon Telegraph and Telephone Corporation.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
#
# ------------------------------------------------------------------
# This file contains modified code from the original RYU file
# ryu/topology/switches.py (ryu-manager version: 4.25)
#
# Modifications:
#   * Added pause resume support to module (temp stop link detection)
# ------------------------------------------------------------------

import logging
import six
import time
import struct

import event
from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import set_ev_cls
from ryu.controller.handler import MAIN_DISPATCHER, DEAD_DISPATCHER
from ryu.lib import addrconv, hub
from ryu.lib.mac import DONTCARE_STR
from ryu.lib.dpid import dpid_to_str, str_to_dpid
from ryu.lib.port_no import port_no_to_str
from ryu.lib.packet import packet, ethernet
from ryu.lib.packet import lldp, ether_types
from ryu.ofproto.ether import ETH_TYPE_LLDP
from ryu.ofproto.ether import ETH_TYPE_CFM
from ryu.ofproto import nx_match
from ryu.ofproto import ofproto_v1_0
from ryu.ofproto import ofproto_v1_2
from ryu.ofproto import ofproto_v1_3
from ryu.ofproto import ofproto_v1_4

# --- Import from the original ryu topo detection module ---
from ryu.topology.switches import Port, Switch, Link, Host
from ryu.topology.switches import HostState, PortState, PortDataState, LinkState
from ryu.topology.switches import LLDPPacket


LOG = logging.getLogger(__name__)


class Host(Host):
    """ Overwrite the host object class to store the name of the host """
    def __init__(self, mac, port, name):
        super(Host, self).__init__(mac, port)
        self.name = name

    def to_dict(self):
        d = {'name': self.name,
             'mac': self.mac,
             'ipv4': self.ipv4,
             'ipv6': self.ipv6,
             'port': self.port.to_dict()}
        return d

    def __eq__(self, host):
        return (self.mac == host.mac and self.port == host.port and
            self.name == host.name)

    def __str__(self):
        msg = 'Host<name=%s, mac=%s, port=%s,' % (self.name, self.mac, str(self.port))
        msg += ','.join(self.ipv4)
        msg += ','.join(self.ipv6)
        msg += '>'
        return msg


class SpecialLinkData():
    """ Class that defines info related to special links (hosts and inter-domian)
    to allow timing out elements.
    """
    def __init__(self, obj):
        self.obj = obj
        self.timestamp = None
        self.received_lldp()


    def is_host(self):
        return isinstance(self.obj, Host)


    def is_inter_dom_link(self):
        return isinstance(self.obj, InterDomPort)


    def received_lldp(self):
        self.timestamp = time.time()

class InterDomPort():
    """ Class that defines information related to a inter domain port (switch and
    port info from other domain).
    """
    def __init__(self, dpid, port_no):
        self.dpid = dpid
        self.port_no = port_no


    def to_dict(self):
        return {'dpid': dpid_to_str(self.dpid),
                'port_no': port_no_to_str(self.port_no)}

    # for Switch.del_port()
    def __eq__(self, other):
        return self.dpid == other.dpid and self.port_no == other.port_no

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return hash((self.dpid, self.port_no))

    def __str__(self):
        return 'InterDomPort<dpid=%s, port_no=%s>' % \
            (self.dpid, self.port_no)


class LLDPPacket(LLDPPacket):

    HOST_NAME_PREFIX = "host:"
    HOST_NAME_FMT = HOST_NAME_PREFIX + "%s"

    @staticmethod
    def lldp_packet(dpid, port_no, dl_addr, ttl):
        pkt = packet.Packet()

        dst = lldp.LLDP_MAC_NEAREST_BRIDGE
        src = dl_addr
        ethertype = ETH_TYPE_LLDP
        eth_pkt = ethernet.ethernet(dst, src, ethertype)
        pkt.add_protocol(eth_pkt)

        tlv_chassis_id = lldp.ChassisID(
            subtype=lldp.ChassisID.SUB_LOCALLY_ASSIGNED,
            chassis_id=(LLDPPacket.CHASSIS_ID_FMT %
                        dpid_to_str(dpid)).encode('ascii'))

        tlv_port_id = lldp.PortID(subtype=lldp.PortID.SUB_PORT_COMPONENT,
                                  port_id=struct.pack(
                                      LLDPPacket.PORT_ID_STR,
                                      port_no))

        tlv_ttl = lldp.TTL(ttl=ttl)
        tlv_end = lldp.End()

        tlvs = (tlv_chassis_id, tlv_port_id, tlv_ttl, tlv_end)
        lldp_pkt = lldp.lldp(tlvs)
        pkt.add_protocol(lldp_pkt)

        pkt.serialize()
        return pkt.data


    @staticmethod
    def lldp_parse(data):
        pkt = packet.Packet(data)
        i = iter(pkt)
        eth_pkt = six.next(i)
        assert type(eth_pkt) == ethernet.ethernet

        lldp_pkt = six.next(i)
        if type(lldp_pkt) != lldp.lldp:
            raise LLDPPacket.LLDPUnknownFormat()

        # Validate and parse the chassis ID
        tlv_chassis_id = lldp_pkt.tlvs[0]
        if tlv_chassis_id.subtype != lldp.ChassisID.SUB_LOCALLY_ASSIGNED:
            raise LLDPPacket.LLDPUnknownFormat(
                msg='unknown chassis id subtype %d' % tlv_chassis_id.subtype)
        chassis_id = tlv_chassis_id.chassis_id.decode('utf-8')
        if not chassis_id.startswith(LLDPPacket.CHASSIS_ID_PREFIX):
            raise LLDPPacket.LLDPUnknownFormat(
                msg='unknown chassis id format %s' % chassis_id)
        src_dpid = str_to_dpid(chassis_id[LLDPPacket.CHASSIS_ID_PREFIX_LEN:])

        # Validate and parse the source Port ID
        tlv_port_id = lldp_pkt.tlvs[1]
        if tlv_port_id.subtype != lldp.PortID.SUB_PORT_COMPONENT:
            raise LLDPPacket.LLDPUnknownFormat(
                msg='unknown port id subtype %d' % tlv_port_id.subtype)
        port_id = tlv_port_id.port_id
        if len(port_id) != LLDPPacket.PORT_ID_SIZE:
            raise LLDPPacket.LLDPUnknownFormat(
                msg='unknown port id %d' % port_id)
        (src_port_no, ) = struct.unpack(LLDPPacket.PORT_ID_STR, port_id)

        # Check if we have a host name (i.e. it's a LLDP host discovery packet)
        system_name = None
        src_addr = None
        if len(lldp_pkt.tlvs) == 6:
            # Extracta and validate the system name
            tlv_system_name = lldp_pkt.tlvs[3]
            if tlv_system_name.__class__ != lldp.SystemName:
                return src_dpid, src_port_no, None
            system_name = tlv_system_name.system_name
            if not system_name.startswith(LLDPPacket.HOST_NAME_PREFIX):
                return src_dpid, src_port_no, None
            system_name = system_name.replace(LLDPPacket.HOST_NAME_PREFIX, "")

            # Extract and validate the address
            tlv_ip = lldp_pkt.tlvs[4]
            if tlv_ip.__class__ != lldp.PortID:
                return src_dpid, src_port_no, None
            if tlv_ip.subtype != lldp.PortID.SUB_NETWORK_ADDRESS:
                return src_dpid, src_port_no, None
            src_addr = tlv_ip.port_id

            # Return the LLDP packet info with the host details tripple
            return src_dpid, src_port_no, (system_name, src_addr, eth_pkt.src)
        else:

            # Return a normal result
            return src_dpid, src_port_no, None


class SwitchesDiscovery(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_0.OFP_VERSION, ofproto_v1_2.OFP_VERSION,
                    ofproto_v1_3.OFP_VERSION, ofproto_v1_4.OFP_VERSION]
    _EVENTS = [event.EventSwitchEnter, event.EventSwitchLeave,
               event.EventSwitchReconnected,
               event.EventPortAdd, event.EventPortDelete,
               event.EventPortModify,
               event.EventLinkAdd, event.EventLinkDelete,
               event.EventHostAdd, event.EventHostDelete,
               event.EventInterDomLinkAdd, event.EventInterDomLinkDelete]

    DEFAULT_TTL = 120  # unused. ignored.
    LLDP_PACKET_LEN = len(LLDPPacket.lldp_packet(0, 0, DONTCARE_STR, 0))

    # Wait n seconds before sending LLDP packet for subsequent ports that need
    # to be polled in a poll interval (prevent packet out request flodding)
    LLDP_SEND_GUARD = .05
    # Every n second flood LLDP discovery packets on every port of every switch
    LLDP_SEND_PERIOD_PER_PORT = .4
    # Check every n seconds for failed ports
    TIMEOUT_CHECK_PERIOD = 2.
    # Link failed if no LLDP packet received after n seconds
    LINK_TIMEOUT = TIMEOUT_CHECK_PERIOD * 2
    # Consider a link as dead if we sent n LLDP packets without reciving any
    LINK_LLDP_DROP = 4


    # XXX ----- EXPLANATION LLDP AND LINK TIMEOUT MECHANISM ----- XXX
    #
    # Generate LLDP packets per port every `LLDP_SEND_PERIOD_PER_PORT` seconds.
    #
    # ``lldp_loop`` checks for expired ports (send LLDP packet) by comparing
    # timestamp with send period. List of ports is ordered where last sent
    # moved to end of list. If in a iteration need to send LLDP packet on
    # multiple ports, delay subseqent packet out commands by `LLDP_SEND_GUARD`
    # seconds. Sleep until signaled or until the next port expires.
    #
    # `link_loop` times out the ports and generates the port down notification.
    # Loop runs every `TIMEOUT_CHECK_PERIOD` seconds. A LLDP link is considered
    # failed if controller sent at-lest `LINK_LLDP_DROP` packets on port but
    # received none. Links expire if no LLDP packet received for `LINK_TIMEOUT`
    # seconds.
    #
    # Default Settings:
    #   LLDP send period is 0.9s, timeout-check period is 5 seconds and link
    #   timeout is set to timeout-check * 2 (10 seconds). This implies that
    #   with default settings we can detect a failed link after 10 seconds
    #   of inactivity.
    #
    # Default Settings Variables:
    #   TimeCheckPeriod = round(LLDPSendPerP * LinkLLDPDrop) = round(4.5) = 5s
    #   LinkTimeout = TimeCheckPeriod * 2 = 5 * 2  = 10s
    #
    # Faster Detection:
    #   LLDPSendPerP = 0.4
    #   LinkLLDPDrop = 4
    #   =>  TimeChekPeriod = round(0.4 * 4) = round(1.6) = 2s
    #       LinkTimeout = 2 * 2 = 4s
    # ---------------------------------------------------------------


    # Declare as failed a host and inter-domain link if an LLDP packet was not
    # received in n seconds.
    HOST_TIMEOUT = 2
    INTER_DOM_LINK_TIMEOUT = 2

    # XXX: The timeout check period is 5 seconds (check every 5 seconds for
    # failed links). A LLDP link is considered failed if the controller sent 5
    # LLDP packets without reciving any LLDP packets. Before we perform the
    # failed link test, we requre that a port did not receive a LLDP packet
    # for 10 seconds (check period * 2). This implies that in reality we
    # can detect that a link has failed after 10 seconds of inactivity.

    def __init__(self, *args, **kwargs):
        super(SwitchesDiscovery, self).__init__(*args, **kwargs)

        self.name = 'topoDiscovery'
        self.dps = {}                 # datapath_id => Datapath class
        self.port_state = {}          # datapath_id => ports
        self.ports = PortDataState()  # Port class -> PortData class
        self.links = LinkState()      # Link class -> timestamp
        self.hosts = HostState()      # mac address -> Host class list
        self.is_active = True
        self.link_discovery = True

        self.special_links = {}

        self.pause_detection = True
        self.pause_detection_state = hub.Event()

        # XXX: If default pause detection overwrite provided, update
        # the flag value.
        if "pause_detection" in kwargs:
            self.pause_detection = kwargs["pause_detection"]

        self.install_flow = self.CONF.install_lldp_flow
        self.explicit_drop = self.CONF.explicit_drop
        self.lldp_event = hub.Event()
        self.link_event = hub.Event()
        self.threads.append(hub.spawn(self.lldp_loop))
        self.threads.append(hub.spawn(self.link_loop))


    @set_ev_cls(event.EventTopoDiscoveryState)
    def topo_discovery_change_state(self, req):
        if req.isPause:
            self._pause()
        else:
            self._resume()

        # Wait up to a second for any in progress LLDP packets
        # to finish
        self.pause_detection_state.wait(timeout=1)
        self.pause_detection_state.clear()

        # Notify the requestor that the operationw as completed
        rep = event.EventTopoDiscoveryStateReply(req.src)
        self.reply_to_request(req, rep)


    def _pause(self):
        self.pause_detection = True


    def _resume(self):
        # TODO: Should we also reset the timestamp for the normal links
        # Reset the timestamps for all links
        for (key, data) in self.special_links.items():
            data.received_lldp()

        self.pause_detection = False
        self.lldp_event.set()


    def close(self):
        self.is_active = False
        if self.link_discovery:
            self.lldp_event.set()
            self.link_event.set()
            hub.joinall(self.threads)


    def _register(self, dp):
        assert dp.id is not None

        self.dps[dp.id] = dp
        if dp.id not in self.port_state:
            self.port_state[dp.id] = PortState()
            for port in dp.ports.values():
                self.port_state[dp.id].add(port.port_no, port)


    def _unregister(self, dp):
        if dp.id in self.dps:
            if (self.dps[dp.id] == dp):
                del self.dps[dp.id]
                del self.port_state[dp.id]


    def _get_switch(self, dpid):
        if dpid in self.dps:
            switch = Switch(self.dps[dpid])
            for ofpport in self.port_state[dpid].values():
                switch.add_port(ofpport)
            return switch


    def _get_port(self, dpid, port_no):
        switch = self._get_switch(dpid)
        if switch:
            for p in switch.ports:
                if p.port_no == port_no:
                    return p


    def _port_added(self, port):
        lldp_data = LLDPPacket.lldp_packet(
            port.dpid, port.port_no, port.hw_addr, self.DEFAULT_TTL)
        self.ports.add_port(port, lldp_data)
        # LOG.debug('_port_added dpid=%s, port_no=%s, live=%s',
        #           port.dpid, port.port_no, port.is_live())


    def _link_down(self, port):
        try:
            dst, rev_link_dst = self.links.port_deleted(port)
        except KeyError:
            # LOG.debug('key error. src=%s, dst=%s',
            #           port, self.links.get_peer(port))
            return
        link = Link(port, dst)
        self.send_event_to_observers(event.EventLinkDelete(link))
        if rev_link_dst:
            rev_link = Link(dst, rev_link_dst)
            self.send_event_to_observers(event.EventLinkDelete(rev_link))
        self.ports.move_front(dst)


    def _special_link_down(self, port):
        """ Remove a special link and generate notifications """
        try:
            data = self.special_links[port]
        except KeyError:
            return

        # Check the type and remove the link correctly
        if data.is_host():
            del self.special_links[port]
            self._host_down(data.obj)
        elif data.is_inter_dom_link():
            del self.special_links[port]
            self._inter_dom_down(port, data.obj)


    def _host_down(self, host):
        """ Notify observers that a host link went down """
        self.send_event_to_observers(event.EventHostDelete(host))
        del self.hosts[host.mac]


    def _inter_dom_down(self, key, idp):
        """ Notify observers that an inter domain link went down """
        inter_dom_link = Link(key, idp)
        self.send_event_to_observers(event.EventInterDomLinkDelete(inter_dom_link))


    def _is_edge_port(self, port):
        for link in self.links:
            if port == link.src or port == link.dst:
                return False

        return True


    @set_ev_cls(ofp_event.EventOFPStateChange,
                [MAIN_DISPATCHER, DEAD_DISPATCHER])
    def state_change_handler(self, ev):
        dp = ev.datapath
        assert dp is not None
        LOG.debug(dp)

        if ev.state == MAIN_DISPATCHER:
            dp_multiple_conns = False
            if dp.id in self.dps:
                LOG.warning('Multiple connections from %s', dpid_to_str(dp.id))
                dp_multiple_conns = True
                (self.dps[dp.id]).close()

            self._register(dp)
            switch = self._get_switch(dp.id)
            LOG.debug('register %s', switch)

            if not dp_multiple_conns:
                self.send_event_to_observers(event.EventSwitchEnter(switch))
            else:
                evt = event.EventSwitchReconnected(switch)
                self.send_event_to_observers(evt)

            if not self.link_discovery:
                return

            if self.install_flow:
                ofproto = dp.ofproto
                ofproto_parser = dp.ofproto_parser

                # TODO:XXX need other versions
                if ofproto.OFP_VERSION == ofproto_v1_0.OFP_VERSION:
                    rule = nx_match.ClsRule()
                    rule.set_dl_dst(addrconv.mac.text_to_bin(
                                    lldp.LLDP_MAC_NEAREST_BRIDGE))
                    rule.set_dl_type(ETH_TYPE_LLDP)
                    actions = [ofproto_parser.OFPActionOutput(
                        ofproto.OFPP_CONTROLLER, self.LLDP_PACKET_LEN)]
                    dp.send_flow_mod(
                        rule=rule, cookie=0, command=ofproto.OFPFC_ADD,
                        idle_timeout=0, hard_timeout=0, actions=actions,
                        priority=0xFFFF)
                elif ofproto.OFP_VERSION >= ofproto_v1_2.OFP_VERSION:
                    match = ofproto_parser.OFPMatch(
                        eth_type=ETH_TYPE_LLDP,
                        eth_dst=lldp.LLDP_MAC_NEAREST_BRIDGE)
                    # OFPCML_NO_BUFFER is set so that the LLDP is not
                    # buffered on switch
                    parser = ofproto_parser
                    actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER,
                                                      ofproto.OFPCML_NO_BUFFER
                                                      )]
                    inst = [parser.OFPInstructionActions(
                            ofproto.OFPIT_APPLY_ACTIONS, actions)]
                    mod = parser.OFPFlowMod(datapath=dp, match=match,
                                            idle_timeout=0, hard_timeout=0,
                                            instructions=inst,
                                            priority=0xFFFF)
                    dp.send_msg(mod)
                else:
                    LOG.error('cannot install flow. unsupported version. %x',
                              dp.ofproto.OFP_VERSION)

            # Do not add ports while dp has multiple connections to controller.
            if not dp_multiple_conns:
                for port in switch.ports:
                    if not port.is_reserved():
                        self._port_added(port)

            self.lldp_event.set()

        elif ev.state == DEAD_DISPATCHER:
            # dp.id is None when datapath dies before handshake
            if dp.id is None:
                return

            switch = self._get_switch(dp.id)
            if switch:
                if switch.dp is dp:
                    self._unregister(dp)
                    LOG.debug('unregister %s', switch)
                    evt = event.EventSwitchLeave(switch)
                    self.send_event_to_observers(evt)

                    if not self.link_discovery:
                        return

                    for port in switch.ports:
                        if not port.is_reserved():
                            self.ports.del_port(port)
                            self._link_down(port)
                    self.lldp_event.set()


    @set_ev_cls(ofp_event.EventOFPPortStatus, MAIN_DISPATCHER)
    def port_status_handler(self, ev):
        msg = ev.msg
        reason = msg.reason
        dp = msg.datapath
        ofpport = msg.desc

        if reason == dp.ofproto.OFPPR_ADD:
            # LOG.debug('A port was added.' +
            #           '(datapath id = %s, port number = %s)',
            #           dp.id, ofpport.port_no)
            self.port_state[dp.id].add(ofpport.port_no, ofpport)
            self.send_event_to_observers(
                event.EventPortAdd(Port(dp.id, dp.ofproto, ofpport)))

            if not self.link_discovery:
                return

            port = self._get_port(dp.id, ofpport.port_no)
            if port and not port.is_reserved():
                self._port_added(port)
                self.lldp_event.set()

        elif reason == dp.ofproto.OFPPR_DELETE:
            # LOG.debug('A port was deleted.' +
            #           '(datapath id = %s, port number = %s)',
            #           dp.id, ofpport.port_no)
            self.send_event_to_observers(
                event.EventPortDelete(Port(dp.id, dp.ofproto, ofpport)))

            if not self.link_discovery:
                return

            port = self._get_port(dp.id, ofpport.port_no)
            if port and not port.is_reserved():
                self.ports.del_port(port)
                self._link_down(port)
                self.lldp_event.set()

            if port in self.special_links:
                self._special_link_down(port)

            self.port_state[dp.id].remove(ofpport.port_no)

        else:
            assert reason == dp.ofproto.OFPPR_MODIFY
            # LOG.debug('A port was modified.' +
            #           '(datapath id = %s, port number = %s)',
            #           dp.id, ofpport.port_no)
            self.port_state[dp.id].modify(ofpport.port_no, ofpport)
            self.send_event_to_observers(
                event.EventPortModify(Port(dp.id, dp.ofproto, ofpport)))

            if not self.link_discovery:
                return

            port = self._get_port(dp.id, ofpport.port_no)
            if port and not port.is_reserved():
                if self.ports.set_down(port):
                    self._link_down(port)
                self.lldp_event.set()

            if (msg.desc.state == dp.ofproto.OFPPS_LINK_DOWN and
                                    port in self.special_links):
                self._special_link_down(port)



    @staticmethod
    def _drop_packet(msg):
        buffer_id = msg.buffer_id
        if buffer_id == msg.datapath.ofproto.OFP_NO_BUFFER:
            return

        dp = msg.datapath
        # TODO:XXX
        if dp.ofproto.OFP_VERSION == ofproto_v1_0.OFP_VERSION:
            dp.send_packet_out(buffer_id, msg.in_port, [])
        elif dp.ofproto.OFP_VERSION >= ofproto_v1_2.OFP_VERSION:
            dp.send_packet_out(buffer_id, msg.match['in_port'], [])
        else:
            LOG.error('cannot drop_packet. unsupported version. %x',
                      dp.ofproto.OFP_VERSION)


    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def lldp_packet_in_handler(self, ev):
        if not self.link_discovery:
            return

        msg = ev.msg
        try:
            src_dpid, src_port_no, host_info = LLDPPacket.lldp_parse(msg.data)
        except LLDPPacket.LLDPUnknownFormat:
            # This handler can receive all the packets which can be
            # not-LLDP packet. Ignore it silently
            return

        # Retrieve the details of the sw that received the LLDP packet (dst)
        dst_dpid = msg.datapath.id
        if msg.datapath.ofproto.OFP_VERSION == ofproto_v1_0.OFP_VERSION:
            dst_port_no = msg.in_port
        elif msg.datapath.ofproto.OFP_VERSION >= ofproto_v1_2.OFP_VERSION:
            dst_port_no = msg.match['in_port']
        else:
            LOG.error('cannot accept LLDP. unsupported version. %x',
                      msg.datapath.ofproto.OFP_VERSION)

        # ------ Host link processing -----

        # Check if this is a host discovery packet
        if host_info is not None:
            # Unpack the host info and create a new host object
            host_name, host_ip, host_mac = host_info
            port = self._get_port(dst_dpid, dst_port_no)
            host = Host(host_mac, port, host_name)

            # If this is a new host add it
            if host_mac not in self.hosts:
                self.hosts.add(host)

                # Set the IP of the host
                if ":" in host_ip:
                    self.hosts.update_ip(host, ip_v6=host_ip)
                else:
                    self.hosts.update_ip(host, ip_v4=host_ip)

                # Notify listeners that a new hosts has connected
                ev = event.EventHostAdd(host)
                self.send_event_to_observers(ev)

                # Add the host to the list of special links
                self.special_links[port] = SpecialLinkData(host)
            elif self.hosts[host_mac].port != port:
                # Set the IP of the host
                if ":" in host_ip:
                    self.hosts.update_ip(host, ip_v6=host_ip)
                else:
                    self.hosts.update_ip(host, ip_v4=host_ip)

                # Move the special link entry to reflect the new port
                del self.special_links[self.hosts[host_mac].port]
                self.special_links[port] = SpecialLinkData(host)

                # Move the host and send event notifying that host has changed
                ev = event.EventHostMove(src=self.hosts[host_mac], dst=host)
                self.hosts[host_mac] = host
                self.send_event_to_observers(ev)
            else:
                self.special_links[port].received_lldp()

            return

        # ------ Inter-domain link processing -----

        src = self._get_port(src_dpid, src_port_no)
        if src and src.dpid == dst_dpid:
            # If the LLDP packet was received on the same switch it was
            # flooded on (loop) ignore it. The packet is neither a normal
            # topo discovery discovery packet or a inter-domain packet
            # (the LLDP port will not exist for inter-domain packets).
            return
        elif not src:
            # Don't know where packet was received so stop
            dst = self._get_port(dst_dpid, dst_port_no)
            if not dst:
                return

            # If the link exists flag that we received a lldp packet for it
            # otherwise add the link
            src = InterDomPort(src_dpid, src_port_no)
            if dst in self.special_links:
                self.special_links[dst].received_lldp()
            else:
                self.special_links[dst] = SpecialLinkData(src)

                # Notify listeners that a new inter-domain link was found
                inter_dom_link = Link(dst, src)
                ev = event.EventInterDomLinkAdd(inter_dom_link)
                self.send_event_to_observers(ev)

            return

        # ------ Standard link (intra-domain) processing -----
        try:
            self.ports.lldp_received(src)
        except KeyError:
            # There are races between EventOFPPacketIn and
            # EventDPPortAdd. So packet-in event can happend before
            # port add event. In that case key error can happend.
            # LOG.debug('lldp_received error', exc_info=True)
            pass

        dst = self._get_port(dst_dpid, dst_port_no)
        if not dst:
            return

        old_peer = self.links.get_peer(src)
        # LOG.debug("Packet-In")
        # LOG.debug("  src=%s", src)
        # LOG.debug("  dst=%s", dst)
        # LOG.debug("  old_peer=%s", old_peer)
        if old_peer and old_peer != dst:
            old_link = Link(src, old_peer)
            del self.links[old_link]
            self.send_event_to_observers(event.EventLinkDelete(old_link))

        link = Link(src, dst)
        if link not in self.links:
            self.send_event_to_observers(event.EventLinkAdd(link))

            # remove hosts if it's not attached to edge port
            host_to_del = []
            for host in self.hosts.values():
                if not self._is_edge_port(host.port):
                    host_to_del.append(host.mac)

            for host_mac in host_to_del:
                del self.hosts[host_mac]

        if not self.links.update_link(src, dst):
            # reverse link is not detected yet.
            # So schedule the check early because it's very likely it's up
            self.ports.move_front(dst)
            self.lldp_event.set()
        if self.explicit_drop:
            self._drop_packet(msg)


    def send_lldp_packet(self, port):
        try:
            port_data = self.ports.lldp_sent(port)
        except KeyError:
            # ports can be modified during our sleep in self.lldp_loop()
            # LOG.debug('send_lld error', exc_info=True)
            return
        if port_data.is_down:
            return

        dp = self.dps.get(port.dpid, None)
        if dp is None:
            # datapath was already deleted
            return

        # LOG.debug('lldp sent dpid=%s, port_no=%d', dp.id, port.port_no)
        # TODO:XXX
        if dp.ofproto.OFP_VERSION == ofproto_v1_0.OFP_VERSION:
            actions = [dp.ofproto_parser.OFPActionOutput(port.port_no)]
            dp.send_packet_out(actions=actions, data=port_data.lldp_data)
        elif dp.ofproto.OFP_VERSION >= ofproto_v1_2.OFP_VERSION:
            actions = [dp.ofproto_parser.OFPActionOutput(port.port_no)]
            out = dp.ofproto_parser.OFPPacketOut(
                datapath=dp, in_port=dp.ofproto.OFPP_CONTROLLER,
                buffer_id=dp.ofproto.OFP_NO_BUFFER, actions=actions,
                data=port_data.lldp_data)
            dp.send_msg(out)
        else:
            LOG.error('cannot send lldp packet. unsupported version. %x',
                      dp.ofproto.OFP_VERSION)


    def lldp_loop(self):
        while self.is_active:
            self.lldp_event.clear()
            if not self.pause_detection:
                now = time.time()
                timeout = None
                ports_now = []
                ports = []
                for (key, data) in self.ports.items():
                    if data.timestamp is None:
                        ports_now.append(key)
                        continue

                    expire = data.timestamp + self.LLDP_SEND_PERIOD_PER_PORT
                    if expire <= now:
                        ports.append(key)
                        continue

                    timeout = expire - now

                    # XXX: Normally, this break would be strange, however, the
                    # port dataset is ordered. When an LLDP packet is sent on
                    # a port, the port is moved to the end of the list. Ports
                    # due for sending packets will queue up at the front so
                    # if the front port is not due for flooding a packet,
                    # subsequent ports will not be due either.
                    break

                for port in ports_now:
                    self.send_lldp_packet(port)
                for port in ports:
                    self.send_lldp_packet(port)
                    hub.sleep(self.LLDP_SEND_GUARD)      # don't burst


                # Check for expired special links
                special_expired = []
                for (key, data) in self.special_links.items():
                    if data.is_host():
                        expire = data.timestamp + self.HOST_TIMEOUT
                        if expire <= now:
                            del self.special_links[key]
                            self._host_down(data.obj)
                    elif data.is_inter_dom_link():
                        expire = data.timestamp + self.INTER_DOM_LINK_TIMEOUT
                        if expire <= now:
                            del self.special_links[key]
                            self._inter_dom_down(key, data.obj)

                if timeout is not None and ports:
                    timeout = 0     # We have already slept
                #LOG.info('lldp sleep %s', timeout)

                # If timeout is None set it to the LLDP send period (never
                # wait indefinetly in case the code deadlocks)
                if timeout is None:
                    timeout = self.LLDP_SEND_PERIOD_PER_PORT

                self.lldp_event.wait(timeout=timeout)
            else:
                self.pause_detection_state.set()
                self.lldp_event.wait()
                self.pause_detection_state.set()


    def link_loop(self):
        while self.is_active:
            self.link_event.clear()

            if not self.pause_detection:
                now = time.time()
                deleted = []
                for (link, timestamp) in self.links.items():
                    # LOG.debug('%s timestamp %d (now %d)', link, timestamp, now)
                    if timestamp + self.LINK_TIMEOUT < now:
                        src = link.src
                        if src in self.ports:
                            port_data = self.ports.get_port(src)
                            # LOG.debug('port_data %s', port_data)
                            if port_data.lldp_dropped() > self.LINK_LLDP_DROP:
                                deleted.append(link)

                for link in deleted:
                    self.links.link_down(link)
                    # LOG.debug('delete %s', link)
                    self.send_event_to_observers(event.EventLinkDelete(link))

                    dst = link.dst
                    rev_link = Link(dst, link.src)
                    if rev_link not in deleted:
                        # It is very likely that the reverse link is also
                        # disconnected. Check it early.
                        expire = now - self.LINK_TIMEOUT
                        self.links.rev_link_set_timestamp(rev_link, expire)
                        if dst in self.ports:
                            self.ports.move_front(dst)
                            self.lldp_event.set()

            self.link_event.wait(timeout=self.TIMEOUT_CHECK_PERIOD)


    @set_ev_cls(event.EventSwitchRequest)
    def switch_request_handler(self, req):
        # LOG.debug(req)
        dpid = req.dpid

        switches = []
        if dpid is None:
            # reply all list
            for dp in self.dps.values():
                switches.append(self._get_switch(dp.id))
        elif dpid in self.dps:
            switches.append(self._get_switch(dpid))

        rep = event.EventSwitchReply(req.src, switches)
        self.reply_to_request(req, rep)


    @set_ev_cls(event.EventLinkRequest)
    def link_request_handler(self, req):
        # LOG.debug(req)
        dpid = req.dpid

        if dpid is None:
            links = self.links
        else:
            links = [link for link in self.links if link.src.dpid == dpid]
        rep = event.EventLinkReply(req.src, dpid, links)
        self.reply_to_request(req, rep)


    @set_ev_cls(event.EventHostRequest)
    def host_request_handler(self, req):
        dpid = req.dpid
        hosts = []
        if dpid is None:
            for mac in self.hosts:
                hosts.append(self.hosts[mac])
        else:
            hosts = self.hosts.get_by_dpid(dpid)

        rep = event.EventHostReply(req.src, dpid, hosts)
        self.reply_to_request(req, rep)
