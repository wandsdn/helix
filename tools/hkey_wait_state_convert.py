#!/usr/bin/env python

# ------------------------------------------------------------------------------------
# Script that takes an old wait_state file and coverts it to the new syntax where
# matches are made up of a two element array where the first entry is the host key pair
# and the second the match with named string arguments where {GID} is replaced with the
# GID computed from the host key pair and {VLAN_GID} the same, however, the set VLAN
# field value added.
#
# Usage:
#   hkey_wait_state_convert <HOST_STR> <IN> <OUT>
#       <HOST_STR>: List of hosts seperated by commars (i.e. h1,h2,h3)
#       <IN>: Input JSON file that contains old wait state
#       <OUT>: Destination JSON file to save converted wait state
# ------------------------------------------------------------------------------------

import sys
import json
import re


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("Usage: %s <HOST_STR> <IN> <OUT>")
        print("\t<HOST_STR> comma seperate list of strings (i.e. h1,h2,h3)")
        print("\t<IN> Input JSON file to convert")
        print("\t<OUT> Output JSON file to save converted check dict")

    hosts_str = sys.argv[1]
    temp_hosts = hosts_str.split(",")
    hosts = []
    for h1 in temp_hosts:
        for h2 in temp_hosts:
            if h1 == h2:
                continue
            hosts.append("%s-%s" % (h1, h2))

    check_dict = {}
    with open(sys.argv[2]) as f:
        check_dict = json.load(f)

    for sw,sw_info in check_dict.iteritems():
        for action,matches in sw_info.iteritems():
            new_matches = []
            for match in matches:
                dl_vlan = -1
                group = -1
                set_field = -1
                group_id = -1

                res = re.search("dl_vlan=(\d+)", match)
                if res:
                    dl_vlan = int(res.group(1))

                res = re.search("group:(\d+)", match)
                if res:
                    group = int(res.group(1))

                res = re.search("set_field:(\d+)", match)
                if res:
                    set_field = 4096 - int(res.group(1))

                res = re.search("group_id=(\d+)", match)
                if res:
                    group_id = int(res.group(1))


                ID = max(dl_vlan, group, set_field, group_id)
                hkey = hosts[ID-1]

                new = re.sub("dl_vlan=(\d+)", "dl_vlan={GID}", match)
                new = re.sub("group:(\d+)", "group:{GID}", new)
                new = re.sub("set_field:(\d+)", "set_field:{VLAN_GID}", new)
                new = re.sub("group_id=(\d+)", "group_id={GID}", new)
                new_matches.append([hkey, new])

            sw_info[action] = new_matches

    with open(sys.argv[3], "w") as f:
        json.dump(check_dict, f, indent=4, sort_keys=True)
