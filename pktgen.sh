#!/bin/bash


# -----------------------------------------------------------
# Generate a constant stream of UDP packets of size 512 with
# a interval of 0.1 ms between each one.
#
# Please note that pktgen will send the packets on prober1-eth
# twords the hardcoded IP 10.0.0.2. Please make sure the target
# PC uses this address
# -----------------------------------------------------------


# Number of CPUS, if more than 2
CPUS=1
# Number of cpies of same packet (0 = same pkt forever)
CLONE_SKB="clone_skb 0"
# Size of a single packet
PKT_SIZE="pkt_size 512"
# Number of pkts to send (0 will send until stopped)
COUNT="count 0"
# Tranmission dellay between packets in nanoseconds (0.1 ms)
DELAY="delay 100000"
# Interface to use to send
ETH="h1-eth0"
MAC=$(ifconfig -a | grep eth0 | cut -d' ' -f 11)

function pgset() {
    local result

    echo $1 > $PGDEV

    result=`cat $PGDEV | fgrep "Result: OK:"`
    if [ "$result" = "" ]; then
        cat $PGDEV | fgrep Result:
    fi
}

for ((processor=0;processor<$CPUS;processor++))
do
    PGDEV=/proc/net/pktgen/kpktgend_$processor
    pgset "rem_device_all"
done

for ((processor=0;processor<$CPUS;processor++))
do
    PGDEV=/proc/net/pktgen/kpktgend_$processor
    pgset "add_device $ETH@$processor"
    PGDEV=/proc/net/pktgen/$ETH@$processor

    # configure
    pgset "$COUNT"
    # One queue per core.
    pgset "flag QUEUE_MAP_CPU"
    pgset "$CLONE_SKB"
    pgset "frags 0"
    pgset "$PKT_SIZE"
    pgset "$DELAY"

    # Set the destination of the packets.
    # You can you use your own range of IPs.
    # IMPORTANT: be aware, you can cause a DoS attack
    # if you flood a machine with so many pack packets.
    pgset "dst 10.0.0.2"

    # Random address with in the min-max range
    #pgset "flag IPDST_RND"
    #pgset "dst_min 127.0.0.0"
    #pgset "dst_max 127.0.0.0"

done

PGDEV=/proc/net/pktgen/pgctrl
# Start the process using pgctrl file
pgset "start"

# You can kill the process remotly using the command
# kill -SIGINT pid_of_script
