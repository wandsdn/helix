#!/bin/bash


# -----------------------------------------------------------
# This script configures a pktgen interface to generate packets
# to a specific destination using PKTGEN.
# To start generating the packets (after running this script)
# run start_pktgen.sh.
#
# Note if you want to send packets to multiple hosts use this
# script as many times as needed to configure multiple interfaces.
#
# Once pktgen has finished you should use cleanup.sh to clean/
# remove the configured pktgen interfaces and stat files.
# -----------------------------------------------------------


function pgset() {
    # Set a PKTGEN device attribute to a proc file. Function
    # outputs the first argument (provided to the method) to
    # the file path $PGDEV. If the operation fails an error
    # message is written to the console.

    local result
    echo $1 > $PGDEV

    result=`cat $PGDEV | fgrep "Result: OK:"`
    if [ "$result" = "" ]; then
        cat $PGDEV | fgrep Result:
    fi
}


# -------------------- APPLICATION ENTRY POINT --------------------


if [ $# -lt 5 ]
then
    echo "Usage $0 <intf> <dst_ip> <delay> <count> <size>"
    echo ""
    echo -e "\t<intf> = Interface i.e. p1-eth0"
    echo -e "\t<dst_ip> = Destination IP of the packets"
    echo -e "\t<delay> = Delay in nanoseconds between packts (100000 = 1ms)"
    echo -e "\t<count> = Number of pakcets to send (0 = until stopped)"
    echo -e "\t<size> = Size of packet in bytes"
    echo -e "\t<cpu_no> = Specify the CPU to use to generate packet stream [DEFAULTS 0]"
    exit;
fi


# CPU to use for packetgen
CPU=0

if [ $# -gt 5 ]
then
    # If the user spcified the CPU argument bind pktgen for this interface
    # to the specified CPU number.
    CPU=$6
fi


CLONE_SKB="clone_skb 0"     # Number of copies of same packet
PKT_SIZE="pkt_size $5"      # Size of packets payload
COUNT="count $4"            # Number of packets to send (0 until stopped)
DELAY="delay $3"            # Delay between packets in nanoseconds
ETH="$1"                    # Interface to send packets on

# Check if the pktgen device already exists
if [ -f /proc/net/pktgen/$ETH@$CPU ]
then
    echo "Removing old device configuration file"
    # Remove the old PKTGEN device config
    PGDEV=/proc/net/pktgen/kpktgend_$CPU
    pgset "rem_device_all"
fi

# Create a new pktgen device and bind it to the specified CPU
echo "Creating pktgen device and binding it to CPU $CPU"
PGDEV=/proc/net/pktgen/kpktgend_$CPU
pgset "add_device $ETH@$CPU"

# Configure the pktgen device
echo "Configuring pktgen device attributes $ETH@$CPU"
PGDEV=/proc/net/pktgen/$ETH@$CPU
pgset "$COUNT"
pgset "flag QUEUE_MAP_CPU"
pgset "$CLONE_SKB"
pgset "frags 0"
pgset "$PKT_SIZE"
pgset "$DELAY"
pgset "dst $2"

# To start PKTGENs packet generation run start_pktgen.sh once all
# interfaces have been configured.
echo "Done"
