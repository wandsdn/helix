#!/usr/bin/env python

""" Generate a wait state json file from the current state of the switches
in the network. The wait state file will have the following syntax:
{
    sw_name: {
        "dump-flows": [
            ...
        ],
        "dump-groups": [
            ...
        ]
    }
}

'sw_name' represents the name of the switch we need to check state of. 'dump-flows'
contains a list of match state entries to check against the flow table of the switch
and 'dump-groups' contains the same thing only for groups. Please note that if any
of the 'dump-flows' or 'dump-groups' lists are empty the section is ommited.

Usage:
    sudo ./GenerateWaitState.py --switches switches --file out_file
        switches - list of switches to generate wait state file for
        out_file - file to save state to
"""

import subprocess
import re
import json
from argparse import ArgumentParser
from collections import OrderedDict


# Skip lines with the following features when generating wait state file
SKIP_FEATURES = [
    "dl_dst=01:80:c2:00:00:0e,dl_type=0x88cc actions=CONTROLLER:65535",
    "OFPST_FLOW reply",
    "OFPST_GROUP_DESC reply",
    "arp actions=move:NXM_OF_ETH_SRC[]->NXM_OF_ETH_DST[],set_field:fb:ff:ff:ff:ff:ff->eth_src,set_field:2->arp_op,move:NXM_NX_ARP_SHA[]->NXM_NX_ARP_THA[],set_field:fb:ff:ff:ff:ff:ff->arp_sha,move:NXM_OF_ARP_TPA[]->NXM_NX_REG0[],move:NXM_OF_ARP_SPA[]->NXM_OF_ARP_TPA[],move:NXM_NX_REG0[]->NXM_OF_ARP_SPA[],IN_PORT"
]

# Run a regex replace on each feature line to replace with specified char.
# Syntax of dict is REGEX_STRING: Replce with chars.
REPLACE_FEATURES = {
    "set_field(:[0-9a-fA-F][0-9a-fA-F]){6}->eth_dst": ".+",
    "nw_dst=([0-9]{1,3}\.){3}[0-9]": ".+"
}


def gen_flow_match(switch):
    """ Retrieve the OF table rules for the `switch` and generate a wait state
    array of features by extracting relevant parts of the OF table flow
    rule lines.

    Args:
        switch (str): Switch to generate wait state mathch array for

    Return:
        Array of wait state line matches from `switch`
    """
    # Retrieve the flow rules of the switch
    match = []
    flows = subprocess.check_output(
        ["ovs-ofctl", "dump-flows", "-O", "OpenFlow13", switch]).split("\n")

    # Iterate through the flow rules
    for line in flows:
        # Check if this is a skip line
        if _skip_line(line):
            continue

        # Extract the feature and add it to the result array
        feature = _extract_flow_feature(line)
        if feature is None or feature == "":
            continue

        # Regex replace what needs to be replaced
        for pat,rep in REPLACE_FEATURES.iteritems():
            feature = re.sub(pat,rep,feature)

        match.append(feature)
    return match


def _get_gid(line):
    gid_search = re.search("group_id=(\d+)", line)
    if gid_search is None:
        return -1

    return int(gid_search.group(1))


def gen_group_match(switch):
    """ Retrieve the OF group table rules for the `switch` and generate a wait
    state array of features by extracting relevant parts of the group table
    line output. Please note that the group match wait state feature lines will
    be ordered by group_id from low to high.

    Args:
        switch (str): Switch to generate wait state mathch array for

    Return:
        Array of wait state line matches from `switch`
    """
    # Retrieve the flow rules of the switch
    match = []
    groups = subprocess.check_output(
        ["ovs-ofctl", "dump-groups", "-O", "OpenFlow13", switch]).split("\n")

    # Iterate through the group table rules
    for line in groups:
        # Check if this is a skip line
        if _skip_line(line):
            continue

        # Extract the feature and add it to the result array
        feature = _extract_group_feature(line)
        if feature is None or feature == "":
            continue

        # Regex replace what needs to be replaced
        for pat,rep in REPLACE_FEATURES.iteritems():
            feature = re.sub(pat,rep,feature)

        match.append(feature)

    sorted_match = sorted(match, key=lambda line: _get_gid(line))
    return sorted_match


def _skip_line(line):
    """ Check if the current line needs to be skiped or ignored when
    creating the wait state list of features.

    Args:
        line (str): Line to check if we need to skip

    Returns:
        bool: True if we need to skip the line, False otherwise
    """
    if len(line) == 0:
        return True

    for skip in SKIP_FEATURES:
        if skip in line:
            return True
    return False


def _extract_flow_feature(line):
    """ Extract a feature from a OpenFlow flow rule line. This method will
    ignore all fields in the line before the priority attribute. Everything
    after will be returned as a feature, this will include actions and matches.

    Args:
        line (str): Line we need to extract feature from

    Returns:
        str: Feature extracted from line or None if line invalid
    """
    match = re.split("priority=\d+[, ]", line)
    if len(match) == 0:
        return None
    return match[1]


def _extract_group_feature(line):
    """ Extract a feature from a OpenFlow group table entry. Method will trim any
    leading and trailing spaces.

    Args:
        line (str): Line we need to extract feature from

    Returns:
        str: Feature extracted from line or None if line invalid
    """
    match = line.rstrip().lstrip()
    if len(match) == 0:
        return None
    return match


def generate_wait_state(switches):
    """ Generate a wait state dictionary for every switch in `switches`.

    Args:
        switches (list of str): Switches we need to generate wait state
            dictionary for.

    Returns:
        dict: Wait state dictionary
    """
    data = {}
    for sw in switches:
        flows = gen_flow_match(sw)
        groups = gen_group_match(sw)

        # Do not add blank switches
        if len(flows) == 0 and len(groups) == 0:
            continue

        data[sw] = {}
        if len(flows) > 0:
            data[sw]["dump-flows"] = flows
        if len(groups) > 0:
            data[sw]["dump-groups"] = groups

    return data


if __name__ == "__main__":
    # Parse the arguments
    parser = ArgumentParser("Generate wait state file")
    parser.add_argument("--switches", required=True, type=str, nargs="+",
            help="Switches to include in wait state file computation")
    parser.add_argument("--file", required=True, type=str,
            help="Output file of wait state for switches")
    args = parser.parse_args()

    # Order the keys in the wait state based on switches arg order
    wait_state = generate_wait_state(args.switches)
    ordered_wait_state = OrderedDict(sorted(wait_state.items(),
            key=lambda (k, v): args.switches.index(k)))

    # Output wait state as JSON to file
    with open(args.file, "w+") as f:
        json.dump(ordered_wait_state, f, indent=4, sort_keys=False)
