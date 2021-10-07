import math
from ShortestPath.dijkstra_te import Graph
import ShortestPath.protection_path_computation as ppc
import topo_discovery.api as topo_disc_api

from TE import TEOptimisation

# Imports used to spoof send and switch for rule extraction
from ryu.ofproto.ofproto_protocol import ProtocolDesc
from ryu.ofproto import ofproto_v1_3
from ryu.topology.switches import Switch


# ---------- OVERRIDE API CALLS USED BY CODE ----------

def send_dummy(req):
    """ Fake send method used to attack to fake DPID object """
    pass

def get_switch(self, dpid=None):
    """ Fake get switch method that returns a fake switch object that dosen't
    have a connection to a device. """
    dummy_prot = ProtocolDesc(ofproto_v1_3.OFP_VERSION)
    dummy_prot.id = dpid
    dummy_prot.send_msg = send_dummy
    dummy_obj = Switch(dummy_prot)
    return[dummy_obj]

# XXX: Overwrite the get switch of the topology discovery API and finally import parent
topo_disc_api.get_switch = get_switch
from ProactiveController import ProactiveController

# --------------------------------------------------

class DummyTEOpti(TEOptimisation):
    def __init__(self, controller, thresh):
        super(DummyTEOpti, self).__init__(controller, thresh, 0,
                            opti_method="FirstSol", candidate_sort_rev=False)

    def _trigger_optimise_timer(self):
        pass

class DummyCtrl(ProactiveController):
    TESTING_MODE = True

    def __init__(self, *args, **kwargs):
        super(DummyCtrl, self).__init__(*args, **kwargs)
        self.computed_paths = {}
        self.TE = DummyTEOpti(self, 0.90)

        self.te_thresh = 0.90
        self.poll_interval = 1

    def get_poll_rate(self):
        return self.poll_interval

    def _install_protection(self):
        """ Overide the default install protection method to compute all
        host-pair paths """
        for host_1 in self.hosts:
            for host_2 in self.hosts:
                if host_1 == host_2:
                    continue

                graph = Graph(self.graph.topo)
                self._compute_paths(graph, host_1, host_2, None, None)

    def compute_path_dict(self, graph, src, dest, inp=None, outp=None, path_key=None):
        """ Save the computed enriched information to a dictionary and return
        the result. The computd paths are removed before adding entry to path info dict
        """
        res = super(DummyCtrl, self).compute_path_dict(graph, src, dest, inp, outp, path_key)
        key = path_key
        if key is None:
            key = (src, dest)

        if key not in self.computed_paths:
            self.computed_paths[key] = {}
        self.computed_paths[key]["primary"] = res["path_primary"]
        self.computed_paths[key]["secondary"] = res["path_secondary"]
        self.computed_paths[key]["splices"] = res["path_splices"]
        return res

    def clear_traffic(self):
        for sw,sw_d in self.graph.topo.iteritems():
            for pn,pn_d in sw_d.iteritems():
                pn_d["poll_stats"] = {"tx_bytes": 0}

    def load_traffic(self, tx_dict):
        """ Load traffic onto the topology using host pair paths """
        link_dict = {}
        path_dict = {}

        # Go through the traffic information and compute the paths for each pair
        for hkey,tx in tx_dict.iteritems():
            src, dst = hkey
            path_info = self.paths[(src, dst)]
            path = ppc.group_table_to_path(path_info, self.graph, path_info["ingress"])

            # Special case, deal with paths of hosts connected to same switch
            if path_info["groups"] == {} and path is None:
                path = [(path_info["ingress"], dst, path_info["out_port"])]

            # Add the host pair send rate to the info dictionary and save the pairs path
            path_dict[hkey] = path
            path_info["stats"] = {"bytes": (tx / 8)}

            # Add pair traffic to all links in it's path
            for hop in path:
                n_from, n_to, n_pn = hop
                port_info = self.graph.get_port_info(n_from, n_pn)
                if (n_from, n_pn) not in link_dict:
                    link_dict[(n_from, n_pn)] = {"hp": [], "cap": port_info["speed"]}
                link_dict[(n_from, n_pn)]["hp"].append((src, dst, tx))

        # Go through host pairs and work out congested links order for traffic adjustment
        con_links = []
        for hkey,path in path_dict.iteritems():
            for hop_i in range(len(path)):
                hop = path[hop_i]
                n_from, n_to, n_pn = hop
                link_info = link_dict[(n_from, n_pn)]

                # Check if the link exceeds capacity
                total = 0
                for hp in link_info["hp"]:
                    total += hp[2]
                if total > link_info["cap"]:
                    # If this link was already detected as congested go to next hop
                    if hop in con_links:
                        continue

                    # Iterate through the congested links and find order based on congested
                    # link position in path. If the cogested link occurs after the current
                    # hop position in the pairs path the hop is inserted at that index in
                    # the congested link.
                    insert_ind = 0
                    for clink_i in range(len(con_links)):
                        clink = con_links[clink_i]
                        if clink in path:
                            ind = path.index(clink)
                            if hop_i < ind:
                                break
                        insert_ind = clink_i + 1

                    con_links.insert(insert_ind, hop)

        # Go through and adjust the congestion rates for the pairs based on fair share forwarding
        # If a node is congested, equal ammounts are taken from each pair based on the total traffic
        # they contribute. This needs to ripple through the links based on the paths of the
        # paris. NOTE: after modification, some links may no longer be congested so we need to
        # always check if they are or not.
        for con_link in con_links:
            n_from, n_to, n_pn = con_link
            link_info = link_dict[(n_from, n_pn)]

            # Check if the link exceeds capacity
            total = 0
            for hp in link_info["hp"]:
                total += hp[2]
            if total > link_info["cap"]:
                # Evenly remove host traffic based on send rates
                for hp_i in range(len(link_info["hp"])):
                    hp = link_info["hp"][hp_i]
                    hp_tx = hp[2]
                    hp_ratio = float(hp_tx) / float(total)
                    diff = total - link_info["cap"]
                    hp_sub = int(math.floor(diff * hp_ratio))
                    new_tx = link_info["hp"][hp_i][2] - hp_sub

                    # Remove the old tuple and re-add it at the exact position
                    del link_info["hp"][hp_i]
                    link_info["hp"].insert(hp_i, (hp[0], hp[1], new_tx))

                    # Adjust the host pair TX for the remaining hops in the path of the pair
                    tmp_path = path_dict[(hp[0], hp[1])]
                    tmp_index = tmp_path.index(con_link)
                    for i in range(tmp_index + 1, len(tmp_path)):
                        tmp_n_from, tmp_n_to, tmp_n_pn = tmp_path[i]
                        tmp_hp = link_dict[(tmp_n_from, tmp_n_pn)]["hp"]
                        # Go through the host pairs on the hop and find the target element
                        # decreasing it's tx send rate
                        for tmp_hp_i in range(len(tmp_hp)):
                            tmp = tmp_hp[tmp_hp_i]
                            if tmp[0] == hp[0] and tmp[1] == hp[1]:
                                # Adjust the TX of the tuple based on the subtraction
                                tmp_new_tx = tmp_hp[tmp_hp_i][2] - hp_sub
                                del tmp_hp[tmp_hp_i]
                                tmp_hp.insert(tmp_hp_i, (tmp[0], tmp[1], tmp_new_tx))

                                # XXX: Assume just one entry per path
                                break

        # Finally go through and assign traffic to the links
        for key,link_info in link_dict.iteritems():
            n_from, n_pn = key
            total = 0
            for hp in link_info["hp"]:
                total += hp[2]
            self.graph.update_port_info(n_from, n_pn, tx_bytes=(total / 8), is_total=False)

if __name__ == "__main__":
    # Initiate the controller, compute paths and validate they are
    # correct.
    topo = {
        "h1": {-1: {"dest": "s1", "destPort": 1, "speed": 1000000000}},
        "h2": {-1: {"dest": "s1", "destPort": 2, "speed": 1000000000}},
        "s1": { 1: {"dest": "h1", "destPort": -1, "speed": 1000000000},
                2: {"dest": "h2", "destPort": -1, "speed": 1000000000},
                3: {"dest": "s2", "destPort": 1, "speed": 1000000000},
                4: {"dest": "s4", "destPort": 1, "speed": 50000000}},
        "s4": { 1: {"dest": "s1", "destPort": 4, "speed": 1000000000},
                2: {"dest": "s2", "destPort": 2, "speed": 1000000000}},
        "s2": { 1: {"dest": "s1", "destPort": 3, "speed": 1000000000},
                2: {"dest": "s4", "destPort": 2, "speed": 1000000000},
                3: {"dest": "s3", "destPort": 1, "speed": 200000000},
                4: {"dest": "s5", "destPort": 1, "speed": 40000000}},
        "s5": { 1: {"dest": "s2", "destPort": 4, "speed": 1000000000},
                2: {"dest": "s3", "destPort": 2, "speed": 1000000000}},
        "s3": { 1: {"dest": "s2", "destPort": 3, "speed": 1000000000},
                2: {"dest": "s5", "destPort": 2, "speed": 1000000000},
                3: {"dest": "h3", "destPort": -1, "speed": 1000000000},
                4: {"dest": "h4", "destPort": -1, "speed": 1000000000}},
        "h3": {-1: {"dest": "s3", "destPort": 2, "speed": 1000000000}},
        "h4": {-1: {"dest": "s3", "destPort": 2, "speed": 1000000000}}}
    hosts = ["h1", "h2", "h3", "h4"]
    obj = DummyCtrl(topo=topo, hosts=hosts)
    obj._install_protection()

    obj.load_traffic({("h1", "h3"): 150000000, ("h2", "h4"): 120000000})

    for sw,sw_d in obj.graph.topo.iteritems():
        print(sw)
        for pn,pn_d in sw_d.iteritems():
            print("\t%s %s" % (pn, pn_d))

    print("\n")

#    for hkey,info in obj.paths.iteritems():
#        print("%s - %s" % (hkey, info))
#    print("\n")

#    for hkey,info in obj.computed_paths.iteritems():
#        print("%s - %s" % (hkey, info))
