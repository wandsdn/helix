#!/bin/bash

CPUS=`grep -c ^processor /proc/cpuinfo`

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
    echo "Removing all devices"
    pgset "rem_device_all"
done

# Un-load the kernel module
rmmod pktgen
echo "Unloaded the pktgen kernel module"
