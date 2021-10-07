#!/usr/bin/python

""" Script which generate LLDP packets to allow host discovery for the controllers.
The script will create a single LLDP packet and send it to the specified socket.

Usage:
    sudo python lldp_host.py iface host_name

    iface = Interface name to send packet on
    host_name = Name of host we are advertising discovery=
"""

import os
import sys
import struct
import time

from socket import *

from ryu.lib.mac import DONTCARE_STR
from ryu.lib.dpid import dpid_to_str
from ryu.ofproto.ether import ETH_TYPE_LLDP
from ryu.lib.packet import packet, ethernet
from ryu.lib.packet import lldp, ether_types


class LLDPPacket(object):
    """ Class which allows the construction of a LLDP packet with specific TLVs.

    Attributes:
        CHASSIS_ID_PREFIX: Prefix added to DPID in chassis ID TLV of LLDP
        CHASSIS_ID_FMT: Format string used to generate the chassis ID with the DPID
        PORT_ID_STR: Format string used to generate the port ID TLV
        HOST_NAME_PREFIX: Prefix added to the system name TLV of the LLDP
        HOST_NAME_FMT: Format string used to generate the host name TLV
    """
    CHASSIS_ID_PREFIX = "dpid:"
    CHASSIS_ID_FMT = CHASSIS_ID_PREFIX + "%s"
    PORT_ID_STR = "!I"
    HOST_NAME_PREFIX = "host:"
    HOST_NAME_FMT = HOST_NAME_PREFIX + "%s"


    @staticmethod
    def lldp_packet(host_pn, host_name, addr, host_dpid=0xffffffff,
                host_mac=DONTCARE_STR, ttl=0):
        """Create a new LLDP packet for host discovery. Packet will have specific
        TLVs based on our host discovery requirements.

        Args:
            host_pn (int): Port of the host that connects to the switch.
            host_name (str): Name of the current host.
            addr (str): IP address of the interface to put in LLDp packet
            host_dpid (int): Datapath ID of the host. For host discovery this has
                to be a unique value (compared to all switches in the network).
                Defaults to a very larger number.
            host_mac (str): MAC address of the host. Defaults to DONTCARE_STR.
            ttl (int): TTL of the LLDP packet. Defaults to 0.

        Returns:
            (bytes): Data of encoded LLDP packet including L2 ethernet framing.
        """

        # Generate a new packet and add eth framing to it
        pkt = packet.Packet()
        dst = lldp.LLDP_MAC_NEAREST_BRIDGE
        src = host_mac
        ethertype = ETH_TYPE_LLDP
        eth_pkt = ethernet.ethernet(dst, src, ethertype)
        pkt.add_protocol(eth_pkt)

        # Generate the LLDP TLVs
        tlv_chassis_id = lldp.ChassisID(
            subtype=lldp.ChassisID.SUB_LOCALLY_ASSIGNED,
            chassis_id=(LLDPPacket.CHASSIS_ID_FMT %
                        dpid_to_str(host_dpid)).encode("ascii"))

        tlv_port_id = lldp.PortID(
            subtype=lldp.PortID.SUB_PORT_COMPONENT,
            port_id=struct.pack(LLDPPacket.PORT_ID_STR, host_pn))

        tlv_system_name = lldp.SystemName(system_name=LLDPPacket.HOST_NAME_FMT
            % host_name)

        tlv_addr = lldp.PortID(subtype=lldp.PortID.SUB_NETWORK_ADDRESS,
            port_id=addr)

        tlv_ttl = lldp.TTL(ttl=ttl)
        tlv_end = lldp.End()

        # Create the LLDP and add it to the packet
        tlvs = (tlv_chassis_id, tlv_port_id, tlv_ttl, tlv_system_name, tlv_addr, tlv_end)
        lldp_pkt = lldp.lldp(tlvs)
        pkt.add_protocol(lldp_pkt)

        # Serialize and return the data of the complated packet
        pkt.serialize()
        return pkt.data


def send_ether(payload, iface):
    """ Send a packet far packet `payload` on interface `iface`. Please
    note that we expect a complete packet including the ethernet framing.

    Args:
        payload (bytes): Packet data
        iface (str): Name of interface to send raw packet on
    """
    s = socket(AF_PACKET, SOCK_RAW)
    s.bind((iface, 0))
    s.send(payload)


if __name__ == "__main__":
    # Validate that we have received the required arguments
    if len(sys.argv) < 3:
        print("Usage: %s iface host_name [run_time] [sleep_time]" % sys.argv[0])
        sys.exit(0)

    # Get the arguments and validate the interface is correct
    hostname = sys.argv[2]
    iface = sys.argv[1]
    run_time = 60
    sleep_time = 0.5

    if len(sys.argv) > 3:
        run_time = int(sys.argv[3])
    if len(sys.argv) > 4:
        sleep_time = float(sys.argv[4])

    # Get the ip address of the specified interface and gen the LLDP packet
    ip_out = os.popen("ip addr show %s" % iface).read()
    try:
        ip_addr = ip_out.split("inet ")[1].split("/")[0]
        eth_addr = ip_out.split("link/ether ")[1].split(" ")[0]
        #ip_addr = ip_out.split("inet ")[1].split(" ")[0]
    except IndexError:
        print ("Iface %s dosen't exist or dosen't have IP!" % iface)
        sys.exit(0)

    packet = LLDPPacket.lldp_packet(1, hostname, ip_addr, host_mac=eth_addr)

    # Send LLDP packets on the specified interface every 0.5 of a second
    # for up to time seconds (or unitl CTRL+C is recived or script terminated) or
    # indefinetly if time is 0 or less.
    if run_time <= 0:
        while True:
            send_ether(packet, iface=iface)
            time.sleep(sleep_time)
    else:
        for i in range(run_time):
            send_ether(packet, iface=iface)
            time.sleep(sleep_time)
