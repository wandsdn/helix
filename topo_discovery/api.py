# Copyright (C) 2013 Nippon Telegraph and Telephone Corporation.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
#
# ------------------------------------------------------------------
# This file contains modified code from the original RYU file
# ryu/topology/api.py (ryu-manager version: 4.25)
# ------------------------------------------------------------------


from ryu.base import app_manager
import event


def get_switch(app, dpid=None):
    """ Retrieve a switch with `dpid` or a list of all switches if `dpid` is
    none.

    Args:
        dpid (obj): ID of switch or None to get all. Defaults to None.

    Returns:
        list: Switch object(s)
    """
    rep = app.send_request(event.EventSwitchRequest(dpid))
    return rep.switches


def get_all_switch(app):
    """ Convience method that returns a list of all switches by calling ``get_switch`` """
    return get_switch(app)


def get_link(app, dpid=None):
    """ Retrieve a list of links that originate at switch with `dpid`. If
    `dpid` is None a list of all links is returned.

    Args:
        dpid (obj): ID of the switch or None to get all. Defaults to none.

    Returns:
        list: List of link objects
    """
    rep = app.send_request(event.EventLinkRequest(dpid))
    return rep.links


def get_all_link(app):
    """ Convience method that returns all links by calling ``get_link`` """
    return get_link(app)


def get_host(app, dpid=None):
    """ Retrieve a list of hosts attached to switch `dpid`. If `dpid` is None all
    hosts are returned.

    Args:
        dpid (obj): ID of the switch or None to get all hosts. Defaults to None.

    Returns:
        list: List of host objects
    """
    rep = app.send_request(event.EventHostRequest(dpid))
    return rep.hosts


def get_all_host(app):
    """ Convience method that returns a list of all hosts by calling ``get_host`` """
    return get_host(app)


# ------------- CUSTOM API EVENTS -----------


def pause_topo_discovery(app):
    """ Send a request to pause topology discovery. Method blocks until the
    operation completes (i.e. the module has paused fully and in progress packet
    output operations have finished)
    """
    rep = app.send_request(event.EventTopoDiscoveryState(True))
    return rep


def resume_topo_discovery(app):
    """ Send a request to resume topology discovery. Method blocks until
    the operation completes (i.e. the module has resumed).
    """
    rep = app.send_request(event.EventTopoDiscoveryState(False))
    return rep
