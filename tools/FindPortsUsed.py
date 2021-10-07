#!/usr/bin/env python

# -----------------------------------------------------------------------
#
# Script that allows finding the ports used by traffic on the switches.
# The flow rules with output ports as well as the group rules with output
# ports will be used to compute the ports used by each specified switch
# to forward traffic. The scripts takes two snashopts of packet counts
# and compares these two to find the ports.
#
# Usage:
#   ./FindGroupPortsUsed.py --wait_enter <wait> --switches <sw>
#
# <wait> = Should the script wait for the user to hit the enter key before
#          computing the second snapshot. Default: False
#
# <sw> = List of switch names to compute path taken for. Default: S1 S2 S3
#        s4 s5.
#
# ----------------------------------------------------------------------

import subprocess
import time
from argparse import ArgumentParser


def get_bucket_ports(switches):
    """ Get the ports that map to each bucket of the `switches`. Command uses the
    'ovs-ofctl dump-groups' 'watch_port' attribute of each bucket as the port mapping.

    Args:
        switches (list of str): switch names to get port mappings

    Returns:
        dict: Port mappings dict in the format {sw: {group: {bucket: port}}}
    """
    bucket_ports = {}
    for sw in switches:
        # Retrieve the group flow rules for the switch
        flows = subprocess.check_output(
            ["ovs-ofctl", "dump-groups", "-O", "OpenFlow13", sw]).split("\n")

        if sw not in bucket_ports:
            bucket_ports[sw] = {}

        # Iterate through the returned output and process it
        for line in flows:
            # Check if the current line is a group entry
            if "group_id" in line:
                line_split = line[1:]
                line_split = line_split.split(",")

                gid = ""
                bucket = 0
                # Iterate through the sections of the line (, seperated)
                for sec in line_split:
                    # Retrieve the group ID from the section
                    if "group_id=" in sec:
                        gid = sec[9:]
                        bucket = 0

                        if gid not in bucket_ports[sw]:
                            bucket_ports[sw][gid] = {}

                    # Get the watchport of the bucket from the section
                    if "bucket=watch_port:" in sec:
                        tmp = sec.split(":")
                        port = tmp[1]

                        # Add the bucket details and go to next port
                        bucket_ports[sw][gid][str(bucket)] = port
                        bucket += 1

    # Return the bucket ports
    return bucket_ports


def get_group_stats(switches):
    """ Return the packet count of each bucket for the specified `switches`. Method
    uses the 'ovs-ofctl dump-group-stats' command.

    Args:
        switches (list of str): switch names to get packet counts for
    Returns:
        dict: Dictionary of packet counts for each bucket in the format
        {sw: {group: {bucket: packet_count}}}.
    """
    stats = {}
    for sw in switches:
        # Retrieve the group stats of the switch
        flows = subprocess.check_output(
            ["ovs-ofctl", "dump-group-stats", "-O", "OpenFlow13", sw]).split("\n")

        if sw not in stats:
            stats[sw] = {}

        # Iterate through the returned output and extract the packet counts
        for line in flows:
            # If the current line has a group ID process it
            if "group_id" in line:
                line_split = line[1:]
                line_split = line_split.split(",")

                gid = ""
                bucket = ""
                # Iterate through the comma seperated values of the line
                for sec in line_split:
                    if "group_id=" in sec:
                        gid = sec[9:]

                        if gid not in stats[sw]:
                            stats[sw][gid] = {}

                    # If the section has a bucket get the packet count
                    if "bucket" in sec:
                        tmp = sec.split(":")
                        bucket = tmp[0]
                        bucket = bucket[6:]

                        packets = tmp[1]
                        packets = packets[13:]

                        stats[sw][gid][bucket] = packets
    # Return the statistics
    return stats


def get_flow_stats(switches):
    """ Get the flow rule packet count for output rules of `switches`. Method
    uses the 'ovs-ofctl dump-flows' command and extracts 'n_packets' for
    rules that contain the action 'output'. If a switch has multiple flow
    rules with the same output port it will sum these values and make a
    single dict entry.

    Args:
        switches (list of str): switches to get flow stats for
    Returns:
        dict: Dictionary of flow stats of syntax {sw: {port: count}}
    """
    stats = {}
    for sw in switches:
        # Retrieve the flow rules of the switch
        flows = subprocess.check_output(
            ["ovs-ofctl", "dump-flows", "-O", "OpenFlow13", sw]).split("\n")

        if sw not in stats:
            stats[sw] = {}

        # Iterate through the returned output and extract the packet counts
        for line in flows:
            # If the current line has an outport process it
            if "output:" in line:
                line_split = line[1:]
                line_split = line_split.split(",")

                packets = ""
                port = ""
                # Iterate through the comma seperated values of the line
                for sec in line_split:
                    if "n_packets=" in sec:
                        packets = sec[11:]

                    # If the section is the output port process the stats
                    if "output:" in sec:
                        port = sec.split("output:")[1]

                        if port in stats[sw]:
                            stats[sw][port] += packets
                        else:
                            stats[sw][port] = packets
    # Return the statistics
    return stats


def find_changed(switches, wait_key=False, time_sleep=2):
    """ Find and return the ports used to output traffic on spcified `switches`.
    The method takes two packet count snapshots seperated either by a enter key
    press or a specified number of seconds see ``Args``. The snapshots are used
    to find differences in the packet counts. If there is a count in snapshot B
    that dosen't exist in A, B is reported as a out-port and the initial count is
    assumed to be 0.

    Args:
        switches (list of str): switch names to find ports of
        wait_key (int, optional): Seperate snapshots by enter key?
            Defaults to False.
        time_sleep (int): number of seconds between snapshots. Defauts
            to 2. Only used if `wait_key` is False.
    Returns:
        list of tupple: ports used by `switches` to send packets
        on. For group rules the `tupple` takes the format (sw, group id, bucket,
        old count, new count), otherwise for flow rules it has the format (sw,
        port, old count, new count). Empty list returned if snapshots have
        the same counts.
    """

    # Get the two snapshots at two second seperation
    gp_stats_a = get_group_stats(switches)
    flow_stats_a = get_flow_stats(switches)

    if wait_key:
        raw_input("Press enter to compute changed!")
    else:
        time.sleep(time_sleep)

    gp_stats_b = get_group_stats(switches)
    flow_stats_b = get_flow_stats(switches)

    # Find the changed group stats by comparing snapshot B with A's packet count
    changed = []
    for sw,sw_val in gp_stats_b.iteritems():
        for gid,gid_val in sw_val.iteritems():
            for bucket,count in gid_val.iteritems():
                if (sw not in gp_stats_a or
                        gid not in gp_stats_a[sw] or
                        bucket not in gp_stats_a[sw][gid]):
                    changed.append((sw, gid, bucket, 0, count))

                if not gp_stats_a[sw][gid][bucket] == count:
                    changed.append((sw, gid, bucket, gp_stats_a[sw][gid][bucket], count))

    # Find the changed flow table out ports stats by looking at snapshot B and comparing
    # with snapshots As packet count.
    for sw,sw_val in flow_stats_b.iteritems():
        for port,count in sw_val.iteritems():
            if (sw not in flow_stats_a or
                    port not in flow_stats_a[sw]):
                changed.append((sw, port, 0, count))

            elif not flow_stats_a[sw][port] == count:
                changed.append((sw, port, flow_stats_a[sw][port], count))

    return changed


def find_changed_tuple(switches, wait_time):
    """ Return the a list of tuples that define the ports traffic use on the
    switches `switches`.

    Args:
        switches (list of str): Name of switches to use when checking path
        wait_time (int): Number of seconds to wait between count snapshot when
            computing path used by traffic.

    Returns:
        list of tuple: List of switch tuples in format (switch, port) that
            define ports traffic uses on switches. The list does not define
            the order of the switches traffic takes (just the ports of each sw).
    """
    ports = get_bucket_ports(switches)
    changed = find_changed(switches, False, time_sleep=wait_time)

    # Iterate through the changed ports
    path = []
    for val in changed:
        sw = None
        port = None
        if (len(val) == 5):
            sw = val[0]
            gid = val[1]
            bucket = val[2]

            port = ports[sw][gid][bucket]
        else:
            sw = val[0]
            port = val[1]
        path.append((sw, port))

    return path


if __name__ == "__main__":
    # Parse the arguments
    parser = ArgumentParser("Find group ports used")
    parser.add_argument("--wait_enter", required=False, action="store_true",
            help="Wait for enter keupress before taking re-checking rules")
    parser.add_argument("--switches", default=["s1", "s2", "s3", "s4", "s5"],
            type=str, nargs="+", help="Switches to check path taken for")
    args = parser.parse_args()

    ports = get_bucket_ports(args.switches)
    changed = find_changed(args.switches, args.wait_enter)

    # Iterate through the changed ports and output them
    for val in changed:
        sw = ""
        port = ""
        if (len(val) == 5):
            sw = val[0]
            gid = val[1]
            bucket = val[2]

            port = ports[sw][gid][bucket]
        else:
            sw = val[0]
            port = val[1]
        print("SW %s uses port %s" % (sw, port))
