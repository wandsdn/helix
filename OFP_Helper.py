#!/usr/bin/python

""" OpenFlow helper module that provides some usefull methods to construct
OF matches and actions based on the datapath OF version of the switch.
"""

from ryu.ofproto import ether
from ryu.lib.packet import lldp
from ryu.ofproto import ofproto_v1_3_parser


def match(dp, vlan=None, in_port=None, ipv4_dst=None, arp=False):
    """ Create an OpenFlow match that will match on either
    VID `vlan` and or in port `in_port`.

    Args:
        dp (controller.Datapath): Switch datapath
        vlan (int): VID to match packets on
        in_port (int): Input port to match packets on
        ipv4_dst (str): IPv4 destination address
        arp (bool): True if want to match ARP packets false otherwise

    Returns:
        OFPMatch: OpenFlow match field for attributes
    """
    match_fields = {}

    if not vlan is None:
        match_fields["vlan_vid"] = vid_present(dp, vlan)
    if not in_port is None:
        match_fields["in_port"] = in_port
    if not ipv4_dst is None:
        match_fields["eth_type"] = ether.ETH_TYPE_IP
        match_fields["ipv4_dst"] = ipv4_dst
    if arp == True:
        match_fields["eth_type"] = ether.ETH_TYPE_ARP

    return dp.ofproto_parser.OFPMatch(**match_fields)


def vid_present(dp, vlan):
    """ Get a VLAN VID with the VID_PRESENT flag set

    Args:
        dp (controller.Datapath): Switch datapath
        vlan (int): VLAN ID

    Returns:
        int: VLAN VID with VID_PRESENT flag set.
    """
    return vlan | dp.ofproto.OFPVID_PRESENT


def do_push_vlan(dp, vlan):
    """ Perform a push vlan operation on the packet.

    Args:
        dp (controller.Datapath): Switch datapath
        vlan (int): VLAN ID to push onto packet.

    Returns:
        List of OFPAction: Push VLAN action list
    """
    return [
        dp.ofproto_parser.OFPActionPushVlan(ether.ETH_TYPE_8021Q),
        dp.ofproto_parser.OFPActionSetField(vlan_vid=vid_present(dp, vlan))
    ]


def do_pop_vlan(dp):
    """ Perform a pop vlan operation on a packet.

    Args:
        dp (controller.Datapath): Switch datapath

    Returns:
        List of OFPAction: Pop VLAN action list
    """
    return [dp.ofproto_parser.OFPActionPopVlan()]


def do_out_port(dp, out_port):
    """ Perform a output to port opration on a packet.

    Args:
        dp (controller.Datapath): Switch datapath
        out_port (int): Port to output packet to

    Returns:
        List of OFPAction: Output to port action list
    """
    return [dp.ofproto_parser.OFPActionOutput(out_port)]


def do_out_group(dp, out_group):
    """ Perform a output to group operation on a packet.

    Args:
        dp (controller.Datapath): Switch datapath
        out_group (int): Group ID to output packet to

    Returns:
        List of OFPAction: Output group action list
    """
    return [dp.ofproto_parser.OFPActionGroup(out_group)]


def do_out_ctrl(dp, buff):
    """ Send `buff` bits of the packet to the controller.

    Args:
        dp (controller.Datapath): Switch datapath
        buff (int): Maximum number of bits to send

    Returns:
        List of OFPAction: Output to port action list
    """
    return [dp.ofproto_parser.OFPActionOutput(dp.ofproto.OFPP_CONTROLLER, max_len=buff)]


def apply_meter(dp, meter_id):
    """ Apply a meter to a flow

    Args:
        dp (controller.Datapath): Switch datapath
        meter_id (int): ID of the meter to apply

    Returns:
        OFPInsturctionMeter: Meter apply instruction
    """
    return dp.ofproto_parser.OFPInstructionMeter(meter_id, dp.ofproto.OFPIT_METER)


def goto_table(dp, table_id):
    """ Send the packet to the table `table_id`.

    Args:
        dp (controller.Datapath): switch datapath
        table_id (int): ID of the table to send packet

    Returns:
        OFPInstructionGotoTable: Go to table instruction
    """
    return dp.ofproto_parser.OFPInstructionGotoTable(table_id)


def set_eth_dst(dp, eth_dst):
    """ Set the ethernet destination on a packet.

    Args:
        dp (controller.Datapath): Switch datapath
        eth_dst (str): Ethernet address to set packets dest to

    Returns:
        List of OFPAction: Set the ethernet destination action list
    """
    return [dp.ofproto_parser.OFPActionSetField(eth_dst=eth_dst)]


def action(dp, vlan_pop=False, vlan=None, eth_dst=None, out_port=None, out_group=None,
            out_ctrl=None):
    """ Perform a set of actions on a packet in the order: pop vlan,
    push vlan, set ethernet destination, output port, output group and
    output controller.

    Args:
        dp (controller.Datapath): Switch datapath
        vlan_pop (bool): Should we pop a VLAN tag. Defaults to False
        vlan (int): VLAN VID to push to packet. Defaults to None
        eth_dst (str): Change the ethernet destination to. Defaults to None
        out_port (int): Port to output packet to. Defaults to None
        out_group (int): Group ID to output packet to. Defaults to None
        out_ctrl (int): Output this many bits of the packet to the controller.

    Returns:
        List of OFPAction: List of actions for specified packet operations.
    """
    inst = []

    if vlan_pop == True:
        inst.extend(do_pop_vlan(dp))
    if not vlan is None:
        inst.extend(do_push_vlan(dp, vlan))
    if not eth_dst is None:
        inst.extend(set_eth_dst(dp, eth_dst))
    if not out_port is None:
        inst.extend(do_out_port(dp, out_port))
    if not out_group is None:
        inst.extend(do_out_group(dp, out_group))
    if not out_ctrl is None:
        inst.extend(do_out_ctrl(dp, out_ctrl))

    return inst


def apply(dp, actions):
    """ Retrieve a OFP apply instructions from a list of `actions`.

    Args:
        dp (controller.Datapath): Switch datapath

    Returns:
        List of OFPInstructionActions: Apply OFP instruction
    """
    return [dp.ofproto_parser.OFPInstructionActions(
                dp.ofproto.OFPIT_APPLY_ACTIONS, actions)]

def arp_fix_action(dp):
    """ Retrive the list of actions that allow for fixing of the ARP problem
    by making the switch re-write a who-is ARP packet to a response packet.

    Args:
        dp (controller.Datapath): Switch datapath

    Returns:
        List of OFPInstructionActions: Respond to ARP requests
    """
    ofp = dp.ofproto
    parser = dp.ofproto_parser

    return [
        parser.NXActionRegMove("eth_src_nxm", "eth_dst_nxm", n_bits=48),
        parser.OFPActionSetField(eth_src="fb:ff:ff:ff:ff:ff"),
        parser.OFPActionSetField(arp_op=0x2),
        parser.NXActionRegMove("arp_sha_nxm", "arp_tha_nxm", n_bits=48),
        parser.OFPActionSetField(arp_sha="fb:ff:ff:ff:ff:ff"),
        parser.NXActionRegMove("arp_tpa_nxm", "reg0", n_bits=32),
        parser.NXActionRegMove("arp_spa_nxm", "arp_tpa_nxm", n_bits=32),
        parser.NXActionRegMove("reg0", "arp_spa_nxm", n_bits=32),
        parser.OFPActionOutput(ofp.OFPP_IN_PORT)]


# The following methods are used for re-installing the LLDP host discovery rule on the
# switches


def lldp_discovery_match(dp):
    """ Return the LLDP host disocvery match rule that matches all LLDP
    packets sent to the nearest bridge MAC

    Args:
        dp (controller.Datapath): Switch datapath

    Returns:
        OFPMatch: OpenFlow match field for LLDP host discovery packets
    """
    return dp.ofproto_parser.OFPMatch(
                eth_type=ether.ETH_TYPE_LLDP,
                eth_dst=lldp.LLDP_MAC_NEAREST_BRIDGE)


def lldp_discovery_action(dp):
    """ Return the LLDP host discovery action that sends all matching LLDP
    packets to the controller to allow host and topology discovery.

    Args:
        dp (controller.Datapath): Switch datapath)

    Returns:
        List of OFPAction: Send packet to the controller
    """
    return [dp.ofproto_parser.OFPActionOutput(dp.ofproto.OFPP_CONTROLLER,
                                dp.ofproto.OFPCML_NO_BUFFER)]


# The following methods are used to offer match and action comparators


def match_obj_eq(a, b, parser=None):
    """ Check if two match objects are the same. Two match objects are the same if they are
    of the same type and the list of actions (items) they contain is the same as well.

    Args:
        a (parser.OFPMatch): First match object to check if `b` matches
        b (parser.OFPMatch): Second match object to check if `a` matches
        parser (ofproto.ofproto_parser): Parser to use for class checking. Defaults to null
            which means that ofproto.ofproto_v1_3_parser will be used.
    """
    if parser is None:
        parser = ofproto_v1_3_parser

    # Check the two objects instances are correct
    if (not isinstance(a, parser.OFPMatch) and
            not isinstance(b, parser.OFPMatch)):
        return False

    # Check the two objects have the same number of match fields
    if len(a.items()) != len(b.items()):
        return False

    # Validate the two match fields are same for both objects
    for item in a.items():
        if item not in b.items():
            return False

    return True


def match_eq(match, fields, parser=None):
    """ Check if a match contains the item list `fields`. In affect this method checks if
    two match objects are the same.

    Args:
        match (parser.OFPMatch): Match to check if it contains the items `fields`
        fields (List of OXMFields): List of fields to check if `match` matches
        parser (parser.ofproto_parser): Parser to use to check for specific object types.
            Defaults to null which means that ofproto.ofproto_v1_3_parser.

    Returns:
        Boolean: True if the match equals, false otherwise
    """
    if parser is None:
        parser = ofproto_v1_3_parser

    if (not isinstance(match, parser.OFPMatch) or not isinstance(fields, list)):
        return False

    return match.items() == fields


def instruction_eq(a, b, parser=None):
    """ Check if two OF instruction arrays or items are equal. An intruction is equal if
    both are of the same type, have the same operation and they both have the same list of
    actions.

    Note:
        Currently only ofproto.OFPInstructionActions and List of ofproto.OFPInstructionActions
    are supported for the comparison. Anything else will return false

    Args:
        a (obj): First instruction to compare to `b`
        b (obj): Second instruction to compare to `a`
        parser (ofproto.ofproto_parser): Parser to use for class match. Defaults to None which
            sets the parser to ofproto.ofproto_v1_3_parser.

    Returns:
        Boolean: True if instructions match, false otherwise
    """
    if parser is None:
        parser = ofproto_v1_3_parser

    # Check if the two instructions share the same type
    if isinstance(a, type(b)) == False:
        return False

    # Check if the instructions are lists
    if isinstance(a, list):
        # Compare the elements legth
        if not len(a) == len(b):
            return False

        # Order the two lists to make comparisons a lot easier
        a = sorted(a)
        b = sorted(b)

        # Iterate through the items in both lists and compare
        for index in range(len(a)):
            if (instruction_eq(a[index], b[index], parser) == False):
                return False

        return True

    # Check if the instructions are actions
    elif isinstance(a, parser.OFPInstructionActions):
        # Make sure the type and length of actions match
        if not a.type == b.type:
            return False
        if not len(a.actions) == len(b.actions):
            return False

        # Sort the action lists of both instructions
        a_actions = sorted(a.actions)
        b_actions = sorted(b.actions)

        # Iterate through the list of actions and check if they are equal
        for index in range(len(a_actions)):
            if not _action_eq(a_actions[index], b_actions[index], parser):
                return False

        return True

    # XXX: Can't match should we raise an unimplemented or just assume everything is okay
    return False


def _action_eq(a, b, parser):
    """ Check if two actions are equal. Two actions are qeual if they are of the same type
    and depending on the type, have the same field or values.
    """
    # If the action is a push vlan match the ethertype
    if isinstance(a, parser.OFPActionPushVlan):
        if not isinstance(b, parser.OFPActionPushVlan):
            return False
        if not a.ethertype == b.ethertype:
            return False
        return True
    # If the action is a set field make sure the key and value match
    elif isinstance(a, parser.OFPActionSetField):
        if not isinstance(b, parser.OFPActionSetField):
            return Fals
        if (not a.key == b.key or not a.value == b.value):
            return False
        return True
    # If the action is a output to group make sure the groups are the same
    elif isinstance(a, parser.OFPActionGroup):
        if not isinstance(b, parser.OFPActionGroup):
            return False
        if not a.group_id == b.group_id:
            return False
        return True
    # If the action is a port output make sure the port is the same
    elif isinstance(a, parser.OFPActionOutput):
        if not isinstance(b, parser.OFPActionOutput):
            return False
        if not a.port == b.port:
            return False
        return True
    else:
        #XXX: What should we do for unknown action types? (for now return false)
        return False
