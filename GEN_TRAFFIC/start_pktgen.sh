#!/bin/bash


# -----------------------------------------------------------
# This script starts pktgen to gen packets based on the configured
# interfaces (./gen_traffic.sh). To terminate pktgen you can
# send a SIGINT to the script or press CTRL+C.
#
# Note, once you have terminated pktgen run the cleanup.sh script
# to clear and unconfigure the interfaces.
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


echo "Starting PKTGEN"
PGDEV=/proc/net/pktgen/pgctrl
pgset "start"
