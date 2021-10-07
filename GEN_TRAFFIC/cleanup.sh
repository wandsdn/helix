#!/bin/bash


# -----------------------------------------------------------
# This script cleans up all configured pktgen devices by removing
# all interfaces from the avaiable CPU cores. Please note that
# the pktgen device info fils will be removed as well (with the
# counts and stats)
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

CPU_COUNT=`ls /proc/net/pktgen/kpktgend_* -l | wc -l`;

echo "Clearing devices for $CPU_COUNT CPUs"
for ((CPU=0;CPU<$CPU_COUNT;CPU++))
do
    PGDEV=/proc/net/pktgen/kpktgend_$CPU
    pgset "rem_device_all"
done

echo "Finished"
