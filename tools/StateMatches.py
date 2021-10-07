#!/usr/bin/env python

import subprocess
import time
import re

check = {
    "s1": {
        "dump-flows": [
            "dl_vlan=1 actions=pop_vlan,output:1",
            "actions=push_vlan:0x8100,set_field:4098->vlan_vid,group:1"
        ],
        "dump-groups": [
            "group_id=1,type=ff,bucket=watch_port:2,actions=output:2,bucket=watch_port:3,actions=output:3"
        ]
    },
}
""" dict: Example of `check_dict`. Syntax of dictionary is a follows:

    {switch: {
        operation: [
            check
        ]
    }

'switch' is the name of the switch we wish to match the state of. 'operation' is defined
as the 'ovs-ofctl' operation we will perform to get the output to check for a list of 'check'
elements. A 'check' element is a regex string used to match for state

Example:
    From the above `:attr:mod(check)` we will check if S1 has a flow rule that matches
    VLAN ID 1 and performs the actions: remove the vlan tag and output on port 1. S1 also
    needs to have a flow rule that pushes a new VLAN tag onto a packet, sets it to a value
    and outputs the packet to group 1. S1 needs to have a group entry for group 1 that is
    a fast failover group type with two ports, 2 and 3. If the ovs-ofctl output for S1 contains
    all of these 'check' elements, S1s state matches.
"""


class StateWaitTimeoutException(Exception):
    """ Exception raised that indicates that a timeout event was encounted by the
    `wait_match` method. The specified state was nevever reached before the timeout
    time.
    """
    pass


def check_match(check_dict):
    """ Check if the current state of the network matches `check_dict`. The method
    uses the command `ovs-ofctl 'op'` to check for the state of the switches.
    In order to validate if the 'state' is the same the method will use a regex
    search to match the output of ovs-ofctl. See ``check``.

    Args:
        check_dict (dict): State to check the network against. See ``check``

    Returns:
        True if the state matches, False otherwise.
    """
    for sw,details in check_dict.iteritems():
        for op,matches in details.iteritems():

            flows = subprocess.check_output(["ovs-ofctl", op, "-O", "OpenFlow13", sw])

            for match in matches:
                if re.search(match, flows) == None:
                    # We have found something that dosen't match
                    return False

    # The current state matches
    return True


def wait_match(check_dict, timeout=0, sleep_time=1):
    """ Wait for the state of the network to match `check_dict`. This method behaves
    silimarly to ``check_match()`` however it will wait up to `timeout` multiples
    of `sleep_time` seconds for the state to match. If the timer expires and the state
    dosen't matches a ``StateWaitTimeoutException`` is raised.

    Args:
        check_dict (dict): State to match. See ``check`` for syntax.
        timeout (int, optional): Time units to wait for state to match. If
            set to 0, wait indefinetly. Otherwise wait up to `sleep_time` seconds
            before raising exception. Defaults to 0.
        sleep_time (int, optional): Time unit in seconds to wait for each timeout count.
            Defaults to 1.

    Returns:
        bool: True if state matches.

    Raises:
        StateWaitTimeoutException: If the state dosen't matches within `timeout`
            multiple `sleep_time` seconds.
    """
    if (timeout >= 0):
        for t in range(timeout):
            # Wait the specified time before we check
            time.sleep(sleep_time)

            # Check if the state matches
            if check_match(check_dict):
                return True
        raise StateWaitTimeoutException
    else:
        while True:
            # Wait the specified time before we check
            time.sleep(sleep_time)

            # Check if the state matches
            if check_match(check_dict):
                return True
