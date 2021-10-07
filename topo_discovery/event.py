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
# ryu/topology/event.py (ryu-manager version: 4.25)
# ------------------------------------------------------------------


from ryu.controller import handler
from ryu.controller import event


class EventSwitchBase(event.EventBase):
    """ Base topo discovery event object realted to switches """
    def __init__(self, switch):
        super(EventSwitchBase, self).__init__()
        self.switch = switch

    def __str__(self):
        return '%s<dpid=%s, %s ports>' % \
            (self.__class__.__name__,
             self.switch.dp.id, len(self.switch.ports))


class EventSwitchEnter(EventSwitchBase):
    """ Event generated when a new switch connects """
    def __init__(self, switch):
        super(EventSwitchEnter, self).__init__(switch)


class EventSwitchLeave(EventSwitchBase):
    """ Event generated when a switch disconnects """
    def __init__(self, switch):
        super(EventSwitchLeave, self).__init__(switch)


class EventSwitchReconnected(EventSwitchBase):
    """ Event generated when a switch reconnects """
    def __init__(self, switch):
        super(EventSwitchReconnected, self).__init__(switch)


class EventPortBase(event.EventBase):
    """ Base topo discovery event object realted to ports """
    def __init__(self, port):
        super(EventPortBase, self).__init__()
        self.port = port

    def __str__(self):
        return '%s<%s>' % (self.__class__.__name__, self.port)


class EventPortAdd(EventPortBase):
    """ Event generated when a new port is detected """
    def __init__(self, port):
        super(EventPortAdd, self).__init__(port)


class EventPortDelete(EventPortBase):
    """ Event generated when a port is removed (dead) """
    def __init__(self, port):
        super(EventPortDelete, self).__init__(port)


class EventPortModify(EventPortBase):
    """ Event generated when the details of a port change """
    def __init__(self, port):
        super(EventPortModify, self).__init__(port)


class EventLinkBase(event.EventBase):
    """ Base topo discovery event object realted to links """
    def __init__(self, link):
        super(EventLinkBase, self).__init__()
        self.link = link

    def __str__(self):
        return '%s<%s>' % (self.__class__.__name__, self.link)


class EventLinkAdd(EventLinkBase):
    """ Event generated when a link is added """
    def __init__(self, link):
        super(EventLinkAdd, self).__init__(link)


class EventLinkDelete(EventLinkBase):
    """ Event generated when a link is deleted """
    def __init__(self, link):
        super(EventLinkDelete, self).__init__(link)


class EventHostBase(event.EventBase):
    """ Base topo discovery event related to hosts """
    def __init__(self, host):
        super(EventHostBase, self).__init__()
        self.host = host

    def __str__(self):
        return '%s<%s>' % (self.__class__.__name__, self.host)


class EventHostAdd(EventHostBase):
    """ Event generated when a new host is detected """
    def __init__(self, host):
        super(EventHostAdd, self).__init__(host)


class EventHostDelete(EventHostBase):
    """ Event generated when a host is removed """
    def __init__(self, host):
        super(EventHostDelete, self).__init__(host)


class EventHostMove(event.EventBase):
    """ Event generated when a host moves to a new port """
    def __init__(self, src, dst):
        super(EventHostMove, self).__init__()
        self.src = src
        self.dst = dst

    def __str__(self):
        return '%s<src=%s, dst=%s>' % (
            self.__class__.__name__, self.src, self.dst)


class EventInterDomLinkAdd(EventLinkBase):
    """ Event generated when a new inter-domain link is detected """
    def __init__(self, link):
        super(EventInterDomLinkAdd, self).__init__(link)


class EventInterDomLinkDelete(EventLinkBase):
    """ Event generated when a inter-domain link times out """
    def __init__(self, link):
        super(EventInterDomLinkDelete, self).__init__(link)


# --- REQUEST DATA FROM THE TOPOLOGY DISCOVERY MODULE ---


class EventSwitchRequest(event.EventRequestBase):
    """ Request a list of switches currently connected """
    def __init__(self, dpid=None):
        super(EventSwitchRequest, self).__init__()
        self.dst = 'topoDiscovery'
        self.dpid = dpid

    def __str__(self):
        return 'EventSwitchRequest<src=%s, dpid=%s>' % \
            (self.src, self.dpid)


class EventSwitchReply(event.EventReplyBase):
    """ Reply sent to the switch request message """
    def __init__(self, dst, switches):
        super(EventSwitchReply, self).__init__(dst)
        self.switches = switches

    def __str__(self):
        return 'EventSwitchReply<dst=%s, %s>' % \
            (self.dst, self.switches)


class EventLinkRequest(event.EventRequestBase):
    """ Request a list of currently connected links """
    def __init__(self, dpid=None):
        super(EventLinkRequest, self).__init__()
        self.dst = 'switches'
        self.dpid = dpid

    def __str__(self):
        return 'EventLinkRequest<src=%s, dpid=%s>' % \
            (self.src, self.dpid)


class EventLinkReply(event.EventReplyBase):
    """ Reply sent to the link request message """
    def __init__(self, dst, dpid, links):
        super(EventLinkReply, self).__init__(dst)
        self.dpid = dpid
        self.links = links

    def __str__(self):
        return 'EventLinkReply<dst=%s, dpid=%s, links=%s>' % \
            (self.dst, self.dpid, len(self.links))


class EventHostRequest(event.EventRequestBase):
    """ Request a list of currently connected hosts """
    def __init__(self, dpid=None):
        super(EventHostRequest, self).__init__()
        self.dst = 'switches'
        self.dpid = dpid

    def __str__(self):
        return 'EventHostRequest<src=%s, dpid=%s>' % \
            (self.src, self.dpid)


class EventHostReply(event.EventReplyBase):
    """ Reply sent to a host request message """
    def __init__(self, dst, dpid, hosts):
        super(EventHostReply, self).__init__(dst)
        self.dpid = dpid
        self.hosts = hosts

    def __str__(self):
        return 'EventHostReply<dst=%s, dpid=%s, hosts=%s>' % \
            (self.dst, self.dpid, len(self.hosts))


# ----------- CUSTOM EVENTS TO PAUSE -----------


class EventTopoDiscoveryState(event.EventRequestBase):
    """ Event used to pause or resume topo discovery """
    def __init__(self, isPause):
        super(EventTopoDiscoveryState, self).__init__()
        self.dst = 'topoDiscovery'
        self.isPause = isPause

    def __str__(self):
        return 'EventTopoDiscoveryStatet<src=%s, isPause=%s>' % \
            (self.src, self.isPause)


class EventTopoDiscoveryStateReply(event.EventReplyBase):
    """ Reply generated that informs when the pause or resume operation completed """
    def __init__(self, dst):
        super(EventTopoDiscoveryStateReply, self).__init__(dst)

    def __str__(self):
        return 'EventTopoDiscoveryStateReply<dst=%s>' % \
            (self.dst)
