#!/user/bin/python

import copy
from threading import Timer
from ShortestPath.dijkstra_te import Graph
from ShortestPath.protection_path_computation import group_table_to_path


class TEOptimisation(object):
    """ TE optimisation module that detects and resolves congestion. Module
    defines several optimisation methods that use different metrics to
    compute a solution set. Congestion is resolved by moving candidates
    (src-dest pairs) paths to avoid using a congested port, reducing its
    usage.

    Attributes:
        over_util (list of tuple): List of congested links in format
            (sw, port).
        optimise_timer (threading.Timer): Timer used to consolidate TE
            optimisation operation.
        controller (HostDiscoveryController): Controller instance that init
            module. Used to retrieve current working paths and other info.
        in_progress (bool): Flag that locks TE optimisation operation.
            indicates if a current TE optimisation is in progress.
        util_thresh (float): A link is declared as congested if its usage is
            over the threshold value (percentage of capacity).
        inter_dom_over_util (dict): Dictionary that holds current congested
            inter-area links where root controller was notified to fix
            congestion. Locks re-optimising inter-area link for n-poll TE
            intervals (value of dictionary). Key in format (sw, port number).
        opti_method (str): Name of TE optimisation to use.
        candidate_sort_rev (bool): Sort source-destination pairs (candidates)
            in descending order (true, default) or ascending (false).
            Candidates are sorted based on traffic sent over congested port.
            If True, heavy hitters will be considered (shifted) first.
        pot_path_sort_rev (bool): Sort potential paths in descending order
            (true) or ascending (false, default) based on primary metric.
            BestSolUsage uses maximum link usage as metric and BestSolPLen
            uses path length (always select shortest first) and usage as a
            tie breaker. Flag only applies for usage metric sorting!
        partial_accept (bool): Allow potential path changes in candidate
            set which partially resolve congestion. A partial solution is
            a path change that pushes any link's usage over the TE threhsold
            but does not cause any congestion loss. Note that if partial
            solutions are accepted (True), if the potential path
            modifications will cause a higher usage of any link on the new
            path compared to the initiail congested port usage (of capacity),
            the solution set is rejected (do not make things worse).
    """

    def __init__(self, controller, thresh, consolidate_time,
                    opti_method="FirstSol", candidate_sort_rev=True,
                    pot_path_sort_rev=False, partial_accept=False):
        """ Intiiate the TE optimisation module and bind the controller instance.

        Args:
            controller (HostDiscoveryController): Controller instance that
                intiatied module.
            thresh (float): Utilisation threshold to decide if link congested
            consolidate_time (float): consolidation time used to delay TE opti
            opti_method (str): Use method to resolve congestion. FirstSol
                (default), BestSolUsage, BestSolPlen, CSPFRecomp.
            partial_accept (bool): Flag that indiciates if partial solutions
                are accepted (link usage > threshold but < link capacity).
                Defaults to false (no partial solutions).
            candidate_sort_rev (bool): Sort src-dest pairs (candidates) in
                reverse order (default True)
            pot_path_sort_rev (bool): Sort potential paths (solution set) in
                revers order (default False)
            partial_accept (bool): Accept partial solutions (default False)
        """
        self.over_utilised = {}
        self.optimise_timer = None
        self.controller = controller
        self.logger = self.controller.logger
        self.in_progress = False
        self.util_thresh = thresh
        self.consolidate_time = consolidate_time
        self.inter_domain_over_util = {}

        # TE optimisation method config attributes
        self.opti_method = opti_method
        self.candidate_sort_rev = candidate_sort_rev
        self.pot_path_sort_rev = pot_path_sort_rev
        self.partial_accept = partial_accept

        # Partial accept does not apply to FirstSol TE opti method. If using
        # first sol and partial accept set to true, raise a warning and
        # change the flag to false.
        if opti_method == "FirstSol":
            self.partial_accept = False
            if partial_accept:
                self.logger.warning("FirstSol TE optimisation method does "
                    "not support partial accepts!")

        # ---- Use the correct TE optimisation methods based on config ----
        if opti_method == "BestSolUsage":
            self.__find_potential_path = self.__findPotentialPath_GroupPortSwap
            self.__apply_fix = self.__applyFix_SwapGroup
        elif opti_method == "BestSolPLen":
            self.__find_potential_path = self.__findPotentialPath_GroupPortSwap
            self.__apply_fix = self.__applyFix_SwapGroup
        elif opti_method == "CSPFRecomp":
            self.__find_potential_path = self.__findPotentialPath_CSPFRecomp
            self.__apply_fix = self.__applyFix_ReinstallPath
        else:
            self.__find_potential_path = self.__findPotentialPath_GroupPortSwap
            self.__apply_fix = self.__applyFix_SwapGroup

    def check_link_congested(self, dpid, port, tx_rate):
        """ Check if a particular link (switch `dpid` port `port`) is congested. Method will
        test if `tx_rate` is greater than `:cls:attr:UTILISATION_THRESH`. If the port is
        congested it's added to the congested list `:cls:attr:(over_utilised)` and
        ``_trigger_optimise_timer()`` is executed.

        Args:
            dpid (int): DPID of the link to check
            port (int): Port of the link to check
            tx_rate (float): Transmission percentage of the ports capacity

        Returns:
            bool: True if the link is over-utilised, false otherwise
        """
        if self.in_progress == True:
            return False

        if tx_rate > self.util_thresh:
            tup = (dpid, port)
            if tup not in self.over_utilised:
                self.over_utilised[tup] = tx_rate
                self._trigger_optimise_timer()
                return True
        return False

    def _trigger_optimise_timer(self):
        """ Reset (if timer in progress) and initiate `:cls:attr:(optimise_timer)` """
        if self.optimise_timer is not None:
            self.optimise_timer.cancel()

        self.optimise_timer = Timer(self.consolidate_time, self._optimise_TE)
        self.optimise_timer.start()

    def _optimise_TE(self):
        """ Consolidtion timer callback method that initiated optimisation operation. Method
        works out source-destination paths that use congested ports and recomputes usage of
        ports based on pair traffic (to account for congestion loss). Finally, the correct
        optimise method is called, based on `:cls:attr:(opti_method)`, to resolve congestion.

        Optimise Method:
            Methods will iteratively try to modify source-destination pair traffic to reduce
        usage on a congested port. If a valid solution is found (congested ports usage is
        below the threshold), the active paths are modified.

        Optimise Methods Inter-Domain Links:
            If a valid solution is found for an inter-domain link, update the paths and
        call ``ctrl_com.notify_egress_change`` method to inform the root controller of any
        egress changes. If a valid soution for inter-domain congestion can't be found,
        call ``ctrl_com.notify_inter_domain_congestion``.

        NOTE:
            Congestion can't be resolved on egress links leading to a destination as the
        controller assumes a single conection to a destination. In this case, if congestion
        is detected on the egress link, ignore it from any further optimisation requests.
        """
        # Clear the optimisation timer, and flat that an operation is in progress
        self.in_progress = True
        self.optimise_timer = None
        paths = self.controller.get_paths()
        topo = self.controller.get_topo()

        # Initiate a local copy of the congested port dictionary
        over_util = {}
        for pt in self.over_utilised.keys():
            # Exclude any egress ports for further considerations
            # XXX: We do not remove the egress port from the list of over-utilised ports
            # so it will not be reconsidered for optimisation as we assume egress ports
            # are fixed and don't change.
            port_info = topo.get_port_info(pt[0], pt[1])
            if port_info["destPort"] == -1:
                continue

            over_util[pt] = {}
            over_util[pt]["traffic_bps"] = 0.0
            over_util[pt]["capacity"] = port_info["speed"]
            over_util[pt]["max_traffic"] = port_info["speed"] * self.util_thresh
            over_util[pt]["paths"] = []

        # Construct the candidate list for the congested ports by iterating
        # through src-dest pairs and checking if they use congested port
        path_cache = {}
        for key,data in paths.iteritems():
            # If source-destination pair has no traffic exclude it
            if "stats" not in data:
                continue

            path_bytes = data["stats"]["bytes"]
            if path_bytes == 0:
                continue

            # Reconstruct the candidate path from the group table ports
            path = None
            if key not in path_cache:
                # XXX: Chache reconstructed path from group table
                ing = data["ingress"]
                path = group_table_to_path(data, topo, ing)
                path_cache[key] = path
            else:
                # XXX: Use chached reconstructed path (already exists)
                path = path_cache[key]

            # Cannot compute path, exclude candidate
            if path is None:
                self.logger.error("Can't reconstruct path %s-%s" % key)
                continue

            # Iterate through the nodes of the pair path and check if it uses
            # an over-utilised port
            for n in path:
                check_key = (n[0], n[2])
                if check_key in over_util:
                    conv = 8.0 / self.controller.get_poll_rate()
                    path_bps = path_bytes * conv
                    over_util[check_key]["traffic_bps"] += path_bps
                    over_util[check_key]["paths"].append((key, path_bps))

        self.logger.info("Over-utilised: %s" % over_util)

        paths = self.controller.get_paths()
        topo = self.controller.get_topo()

        # Try to fix resolve congestion by reducing usage of congested links
        for con_link,con_link_data in over_util.iteritems():
            self.logger.info("Trying to fix congestion on SW %s port %s" %
                                                (con_link[0], con_link[1]))
            con_fix = []
            found_valid_partial = False
            invalid_solution_set = False
            g = Graph(topo.topo)
            is_inter_domain_link = self.controller.is_inter_domain_link(
                                                    con_link[0], con_link[1])

            # TODO FIXME: We are checking if a candidate no longer uses
            # the congested port, but what about a new candidate that uses
            # it due to previous modifications? A better solution to this
            # is to build the candidate set on the fly when we iterate
            # instead of doing the subsequent check !!!

            # If the any candidate no longer uses the congested port, remove
            # it from the candidate set and reduce the total usage. A previous
            # modification may have shifted traffic away.
            self._check_already_avoids_link(g, paths, con_link, con_link_data)

            # XXX: Remove congested port from global over-utilised list.
            # Port removed even if congestion was not resolved to allow
            # re-checking during the next poll interval.
            del self.over_utilised[con_link]

            # Sort the candidates based on usage of congested port
            con_link_data["paths"] = sorted(con_link_data["paths"],
                                                key=lambda util: util[1],
                                                reverse=self.candidate_sort_rev)
            self.logger.info("\tCandidates: %s" % con_link_data["paths"])

            if len(con_link_data["paths"]) == 0:
                self.logger.info("\tCan't fix congestion on SW %s Port %s,"
                        " no candidates found!" % (con_link[0], con_link[1]))
                # FIXME TODO: Because we do not have enough paths we cannot
                # ask the root controller to optimise ... should we try to
                # modify this behaivour ???
                continue

            # Make a copy of the initial traffic value on the congested port
            # to allow checking for partial solutions and calling the root
            # controller to resolve inter-domain congestion on failure
            con_link_data["startTraffic_bps"] = con_link_data["traffic_bps"]

            # Iterate through candidates of congested port
            for candidate,candidate_usage in con_link_data["paths"]:
                # If the port is lon longer congested, stop iterating throuhg
                # the candidates
                if con_link_data["traffic_bps"] <= con_link_data["max_traffic"]:
                    break

                # Get the candidate path information
                candidate_info = paths[candidate]
                candidate_tx_bytes = candidate_info["stats"]["bytes"]
                candidate_ing = candidate_info["ingress"]
                candidate_path = group_table_to_path(candidate_info, g,
                                                            candidate_ing)
                self.logger.info("\tCandidate %s - %s" % candidate)
                self.logger.info("\tCurrent Path: %s" % candidate_path)

                # Find a potential path change (check if we can
                # modify candidte path to reduce usage on congested port)
                candidate_mod = self.__find_potential_path(g, con_link,
                                        candidate, candidate_path,
                                        candidate_info, candidate_usage)

                # If no solution was found, consider next candidate
                if candidate_mod is None:
                    self.logger.info("\tCan't use candidate (%s-%s)"
                                        " to reduce usage" % candidate)
                    continue

                # Add the candidate modification to the solution set, decrease
                # congested port usage and update topology traffic based on
                # the proposed path change (temporary topology not global)
                swap_link, new_path = candidate_mod
                con_link_data["traffic_bps"] -= candidate_usage
                con_fix.append((candidate, candidate_path, new_path,
                                        swap_link, candidate_tx_bytes))

                update_link_traffic(g, candidate_path, new_path,
                                            candidate_tx_bytes, self.logger)


            # XXX: -------- CHECK THE SOLUTION SET AND APPLY IF OK --------


            # Calculate the congested link spare capacity (based on the speed)
            # and check if solution set is invalid
            con_spare_of_cap = (con_link_data["capacity"] -
                                            con_link_data["startTraffic_bps"])
            if len(con_fix) > 0 and self.partial_accept:
                # Get min spare capacity of solution set (new links)
                min_spare = find_solset_min_spare_capacity(g, con_fix,
                                self.logger,
                                te_thresh=self.util_thresh,
                                poll_rate=self.controller.get_poll_rate())

                self.logger.info("CON PORT INIT SPARE: %s | NEW SPARE: %s" %
                                        (con_spare_of_cap, str(min_spare)))

                # If the solution set introduces new congestion without loss,
                # invalidate the solution set if spare capacity is less than
                # the previous congestion rate on the port (do not make things
                # worse).
                # See issue #136 for some details and how this mechanisms will
                # behave with a reverse potential path sort of True!
                if min_spare[0] < 0 and min_spare[1] <= con_spare_of_cap:
                    self.logger.info("Solset introduces more congestion."
                                        " Invalidating solution set!")
                    invalid_solution_set = True

                # Check if we have a valid partial solution. A partial sol
                # is a set of modifications that reduces the overall
                # congestion rate in the network (the new max con rate is
                # lower than current con port rate). A partial can only occur
                # if the current con link rate is > max traffic (over
                # te-threshold) but under the links capacity (no loss).
                if (not invalid_solution_set and
                                        con_link_data["traffic_bps"] >
                                        con_link_data["max_traffic"] and
                                        con_link_data["traffic_bps"] <=
                                        con_link_data["capacity"]):
                    self.logger.info("\tValid partial solution!")
                    found_valid_partial = True

            # If a solution for congestion was found apply all modifications
            if (len(con_fix) > 0 and not invalid_solution_set and
                        (con_link_data["traffic_bps"] <=
                        con_link_data["max_traffic"] or found_valid_partial)):
                self.logger.info("\tFound congestion fix for sw %s pn %s" %
                                                (con_link[0], con_link[1]))
                self.logger.info("\tSolution: %s" % con_fix)

                # Go through fix list and implement candidate changes
                for swp in con_fix:
                    self.__apply_fix(topo, swp)
            else:
                self.logger.info("\tCan't fix congestion on SW %s PN %s" %
                                                (con_link[0], con_link[1]))

                # If this is an inter-domain link, request a root controller
                # optimisation (inter-domain optimisation failed)
                if is_inter_domain_link:
                    self.logger.info("\tThis is an inter-domain link!")
                    self.controller.ctrl_com.notify_inter_domain_congestion(
                            con_link[0], con_link[1],
                            con_link_data["startTraffic_bps"],
                            con_link_data["paths"]
                    )
                    self.inter_domain_over_util[(con_link[0], con_link[1])] = 2

        # We have finished, chnage the in progress flag
        self.in_progress = False


    # ------ APPLY POTENTIAL PATH CHANGE METHODS ------


    def __applyFix_SwapGroup(self, topo, congestion_fix):
        """ Apply a congestion fix by modifying the specified groups of a
        particular port. This method is used to apply the candidate paths
        generated by the FirstSol, BestSolUsage and BestSolPLen methods.

        Args:
            topo (topology): Global topology graph. Used to update traffic
                based on candidate send rate.
            congestion_fix (tuple): Congestion fix information in format
                (key, old_path, new_path, node, bytes) where key, old_path
                and bytes represent the candidate key, old used path and
                bytes generated, while node is the swap node in format
                (sw, new primary port of group) and new_path represents the
                candidate path. Paths encoded as a list of triple in format
                (sw_from, sw_to, port). See ```group_table_to_path```.
        """
        paths = self.controller.get_paths()

        cndt, cndt_path, new_path, node, cndt_tx = congestion_fix
        gid = paths[cndt]["gid"]
        self.controller.invert_group_ports(cndt, node, gid)

        # Update usage of topology based on implemented solution
        update_link_traffic(topo, cndt_path, new_path, cndt_tx, self.logger)

        # If modified an inter-area path (candidate) update the ingress and
        # notify the root controller of any changes
        if cndt in self.controller.ctrl_com.inter_dom_paths:
            new_egress = new_path[len(new_path)-1]

            new_egress = (new_egress[0], new_egress[2])
            # FIXME: Maybe provide a method to trigger a egress change rather
            # than manually modifying it ...
            paths[cndt]["egress"] = new_egress
            self.controller.ctrl_com.notify_egress_change(cndt, new_egress)

    def __applyFix_ReinstallPath(self, topo, congestion_fix):
        """ Apply a congestion fix by installing a recomputed path info
        dictionary. This method is used for CSPFRecomp method. See
        ``__applyFix_SwapGroup`` for list of args. The ``node`` element
        of `congestion_fix` will contain the new path dictionary that
        needs to be installed.
        """
        paths = self.controller.get_paths()

        cndt, cndt_path, new_path, new_dict, cndt_tx = congestion_fix
        gp = {}
        special_flows = {}
        g = Graph(topo.topo)

        # Remove any indirection group or special flow entries from the
        # new path dictionary
        for key in new_dict["groups"].keys():
            if isinstance(key, str) and key.startswith("*"):
                del new_dict["groups"][key]
        for key in new_dict["special_flows"].keys():
            if isinstance(key, str) and key.startswith("*"):
                del new_dict["special_flows"][key]
        # Remove the last node in the new path if its a dummy indirection
        # node
        if (isinstance(new_path[-1][0], str) and
                                        new_path[-1][0].startswith("*")):
            new_path = new_path[:-1]

        # If this is an inter-area path compute the backup paths based on the
        # received path instructions.
        if cndt in self.controller.ctrl_com.inter_dom_paths:
            # NOTE: We call notify root egress before computing the secondary
            # inter-area path because the method will automatically update the
            # root instructions with the correct egress.
            if cndt[1] not in self.controller.hosts:
                self.controller.ctrl_com.notify_egress_change(cndt,
                                                        new_dict["egress"])

            # Compute the secondary paths for the inter-domain path segment
            idp = self.controller.ctrl_com.inter_dom_paths[cndt]
            target_names = self.controller.add_dummy_destination(cndt, idp, g)
            gp, special_flows, _ = self.controller.compute_path_segment_secondary_paths(
                                        cndt, idp, target_names, g)

        # XXX: Copy the stats to the new CSPF path (ensures no failures when
        # optimising next port)
        new_dict["stats"] = paths[cndt]["stats"]

        # Install the path modifications and update the link traffic
        new_dict["address"] = paths[cndt]["address"]
        new_dict["eth"] = paths[cndt]["eth"]
        self.controller.install_path_dict(cndt, new_dict, combine_gp=gp,
                                        combine_special_flows=special_flows)
        update_link_traffic(topo, cndt_path, new_path, cndt_tx, self.logger)


    # ------ FIND POTENTIAL PATH CHANGE METHODS ------


    def __findPotentialPath_GroupPortSwap(self, g, con_link,
                                                c, c_path, c_info, c_usage):
        """ Generate solution path for candidate `c` (src-dest pair) by
        swaping ports of groups. For every switch in `c_path` check check
        alternative ports in groups. If TE-opti method is FirstSol return
        first valid group swap that avoids using congested link `con_link`
        and does not introduce new congestion. If BestSolUsage and BestSolPLen
        generate set of all potential modificiations and return best option.
        For BestSolUsage select potential candidate modification which either
        minimises link usage (`:mod:attr:(pot_path_sort_rev)` set to True) or
        maximises (flag set to false). A solution that minimises link usage
        will maximise spare capacity (flag is inverted as metric is inverted).
        For BestSolPlen always selects shortest path first while max usage is
        used as a tie break. Flag only accepts link usage criteria.

        NOTE: Partial accept does not apply to FirstSol and for other two
        methods, solutions which push links over threshold but under max
        speed are accepted. Sort order flag will affect potential path
        selection such that if flag set to True, a partial solution will
        be selected over a non-partial (i.e. partial solutions will have
        higher max link usages by definition or lower spare capacity)!

        Args:
            g (topology): Topology to use for path recomputations
            con_link (tuple): Congested link in format (sw, port)
            c (tuple of node): Candidate key in format (src, dest)
            c_path (list of node): Current candidate path
            c_info (dict): Source-destination pair installed path info
            c_usage (float): Traffic candidate is generating in bits/s

        Returns:
            (tuple, list of node): None if no potential path found or a tuple
                containing the port where the group is inverted and new path.
        """
        self.logger.info("%s | %s | %s | %s" % (self.opti_method,
                                                self.candidate_sort_rev,
                                                self.pot_path_sort_rev,
                                                self.partial_accept))

        # Get the ingress of the candidate from the info dictionary
        c_ing = c_info["ingress"]
        solution_set = []

        # TODO: We may need a way to deal with path modifications due
        # to failures, i.e. what if the over-util is on the secondary
        # and not the primary. Group entries should update so this may
        # not be a problem.
        # Iterate through every hop of the candidate path
        for i in range(len(c_path)):
            node = c_path[i][0]

            # Stop iterating if we have passed the congested link (can't fix)
            if i > 0 and c_path[i-1] == con_link[0]:
                self.logger.info("\tPassed congested link in candidate path,"
                                                        " stopping check!")
                break

            if node in c_info["groups"]:
                # Sanitize group ports (remove inactive ports)
                gp = []
                for p in c_info["groups"][node]:
                    if g.get_port_info(node, p) is not None:
                        gp.append(p)

                if len(gp) > 1:
                    # Go through alternative ports in group and check for a
                    # valid candidate potential path
                    for alt_port in gp[1:]:
                        # Compute a new potential path
                        pot_path = group_table_to_path(c_info, g, c_ing,
                                old=c_path, swap=(node, gp[0], alt_port))

                        if pot_path is None:
                            self.logger.info("\tCan't swap group at (%s, %s),"
                                        " invalid path" % (node, alt_port))
                            continue

                        # Check if potential path is valid (avoids congested
                        # port and does not cause further congestion)
                        if self._path_avoids_link(pot_path, con_link):
                            self.logger.info("\tSwaping group at (%s, %s)"
                                        " avoids link" % (node, alt_port))
                            min_spare = self._swap_utilisation(g, c_path,
                                                        pot_path, c_usage)
                            if min_spare[0] < 0:
                                self.logger.info("\tSwap group at (%s, %s)"
                                        "causes new congestion" %
                                                        (node, alt_port))

                                # If flag true, accept partial potential path
                                # change if no congestion loss occurs
                                if (self.partial_accept and min_spare[1] >= 0):
                                    self.logger.info("\tSwap group is a"
                                                        " partial solution")

                                    if self.opti_method == "BestSolUsage":
                                        solution_set.append((
                                                (node, alt_port),
                                                pot_path, min_spare
                                        ))
                                    elif self.opti_method == "BestSolPLen":
                                        solution_set.append((
                                                (node, alt_port),
                                                pot_path,
                                                (len(pot_path), min_spare)
                                        ))
                                    else:
                                        # CRITICAL ERROR, FirstSol should not
                                        # have partial flag set to true
                                        self.logger.critical("\tERROR:"
                                                " FirstSol should not allow"
                                                " partials!")
                                        continue

                            else:
                                self.logger.info("\tSwapping group at "
                                            "(%s, %s) ok" % (node, alt_port))

                                if self.opti_method == "BestSolUsage":
                                    solution_set.append((
                                            (node, alt_port),
                                            pot_path, min_spare
                                    ))
                                elif self.opti_method == "BestSolPLen":
                                    solution_set.append((
                                            (node, alt_port),
                                            pot_path,
                                            (len(pot_path), min_spare)
                                    ))
                                else:
                                    # Assume FirstSol and just return the
                                    # first result
                                    self.logger.info("\tFirstSol, return "
                                            " the first result!")
                                    return ((node, alt_port), pot_path)

                        else:
                             self.logger.info("\tSwaping group at (%s, %s)"
                                    " dosen't avoid link" % (node, alt_port))

        # No potential path changes were found
        if len(solution_set) == 0:
            return None

        # Sort the solution set and select the best solution for the candidate
        # NOTE: Sort rev is inverted as True -> max usage is the min spare
        # cappactiy and False -> min usage is the max spare capacity
        if self.opti_method == "BestSolUsage":
            # Sort based on the spare capacity on the links of the potential
            # path
            solution_set = sorted(solution_set, key=lambda util: util[2][0],
                                    reverse=(not self.pot_path_sort_rev))
        elif self.opti_method == "BestSolPLen":
            # First sort based on the spare capacity and then length of path
            # (primary selection metric).
            solution_set = sorted(solution_set,
                key=lambda util: util[2][1][0],
                reverse=(not self.pot_path_sort_rev)
            )
            solution_set = sorted(solution_set, key=lambda util: util[2][0])
        else:
            # XXX: Should never reach this point!
            self.logger.critical("ERROR: FirstSol should not have an entry in"
                                                            " solution set!")
            return None

        best = solution_set[0]
        return (best[0], best[1])

    def __findPotentialPath_CSPFRecomp(self, g, con_link,
                                                c, c_path, c_info, c_usage):
        """ Find a potential candidate path change using the CSPFRecomp TE
        optimisation method. See ``__findPotentialPath_FirstSol`` for list of
        args and return attributes. Method uses a CSPF style recomputation
        to recompute the candidates paths. First, the method will prune
        the topology of the congested links and any links that do not have
        sufficient headroom to carry candidate traffic. After pruning a new
        path is computed for the candidate. If partial accept flag set, the
        method will prune a link from the topology only if moving the
        candidate traffic will cause packet loss (allows using links over
        the usage specified by threshold but under the links speed).

        NOTE: For iter-area candidates, the method will compute and fix
        the ingress/egress (if applicable), as well as copy the ingress
        change detection ports (if applicable).
        """
        self.logger.info("CSPFRecomp | %s" % (self.pot_path_sort_rev))

        # Get the ingress of the candidate from the info dictionary and
        # work out the source and destination of the new path
        pt_from,pt_to = c
        if pt_from not in self.controller.hosts:
            pt_from = c_info["ingress"][0]

        # Initiate a temporary topology and add fake nodes if the candidate
        # needs an inter-area path and this is not a destination segment
        g_tmp = Graph(g.topo)
        if pt_to not in self.controller.hosts:
            idp = self.controller.ctrl_com.inter_dom_paths[c]
            pt_to = "TARGET"
            index = 1
            for tmp in idp:
                # XXX: Add a indirection node to the target to allow the
                # CSPF algorithm to use any egress port (i.e. prevent
                # merging).
                idp_out_sw, idp_out_port = tmp["out"]
                indirect = "*INDIRECT_%s" % index
                g_tmp.topo[idp_out_sw][idp_out_port]["dest"] = indirect
                g_tmp.topo_stale = True
                g_tmp.add_link(indirect, pt_to, -1, -1)
                self.logger.info("Add indirect node %s to (%s,%s)" %
                                    (indirect, idp_out_sw, idp_out_port))
                index = index + 1

        # Make a copy of the topology to compute the secondary path and
        # splice (backup can use con elements to increase protection
        # coverage).
        g_tmp_sec = Graph(g_tmp.topo)

        # Perform a CSPF prune of the topology
        CSPFPrune(g_tmp, con_link, c_path, c_usage, self.logger,
                                te_thresh=self.util_thresh,
                                poll_rate=self.controller.get_poll_rate(),
                                paccept=self.partial_accept)

        # Recompute the candidate path (potential path) using the pruned
        # topology graph (compute a path information dictionary)
        new_dict = self.controller.compute_path_dict(g_tmp, pt_from,
                                pt_to, path_key=c, graph_sec=g_tmp_sec)

        # If a potential path was found (dictionary not empty), return it
        if len(new_dict) > 0:
            self.logger.info("\tPath %s is okay" % new_dict["path_primary"])
            new_dict["gid"] = c_info["gid"]

            # Work out the correct ingress for inter-area paths
            if new_dict["ingress"] is None:
                new_dict["ingress"] = c_info["ingress"]
                new_dict["in_port"] = c_info["in_port"]

            # Work out the correct egress for inter-area paths
            if new_dict["egress"] is None:
                penultim =  g_tmp.flows_for_path(new_dict["path_primary"])[-2]
                new_dict["egress"] = (penultim[0], penultim[2])
                new_dict["out_port"] = penultim[2]

            # If old dictionary contains ingress change ports make a copy
            # NOTE that ingress cannot be modified via CSPF recomputation !
            if "ingress_change_detect" in c_info:
                new_dict["ingress_change_detect"] = c_info["ingress_change_detect"]

            prim_path = group_table_to_path(new_dict, g, new_dict["ingress"])

            self.logger.info("\tOld Dict: %s" % self.controller.paths[c])
            self.logger.info("\tNew Dict: %s" % new_dict)
            self.logger.info("\tNew Path: %s" % prim_path)
            return (new_dict, prim_path)

        return None


    # ------ HELPER METHODS ------


    def _path_avoids_link(self, path, link):
        """ Check if `path` does not contains `link`.

        Args:
            path (list): Path as list of (from_sw, to_sw, out_port)
            link (tuple): Link to check in format (sw, port)

        Returns:
            bool: False if `path` contains `link, or True otherwise.
        """
        for p in path:
            if p[0] == link[0] and p[2] == link[1]:
                return False
        return True

    def _swap_utilisation(self, g, old_path, new_path, tx_bps):
        """ Return the maximum usage (minimum spare capacity) of links in
        `new_path` when moving `tx_bps` average traffic from `old_path`.
        For every unique link in `new_path`, method adds `tx_bps` traffic
        to current link traffic (`tx_bps` not included on path).

        Args:
            g (Graph): Graph representation of the network topology
            old_path (list of trile): Old path in format (sw_from, sw_to, out_port).
            new_path (list of triple): New path in format (sw_from, sw_to, out_port).
            tx_bps (float): Traffic in bps to move onto `new_path` (AVG converted).

        Returns:
            (float, float): Packed average bps values which show - minimum
                spare capacity of link up to TE threshold and of complete
                link speed (maximum traffic link can carry). Values account
                for poll-interval (averages per second). Min spare capacity
                represents the maximum usage on the path
        """
        min_spare = None
        for node in new_path:
            # Get the information of the port and check if everything is there
            port_info = g.get_port_info(node[0], node[2])
            if (port_info is None or "speed" not in port_info or
                                            "poll_stats" not in port_info):
                self.logger.info("Port %s sw %s dosen't have required fields"
                                                        % (node[2], node[0]))
                continue

            # Get the current traffic on the port and compute port info
            port_speed = port_info["speed"]
            conv = 8.0 / self.controller.get_poll_rate()
            total_bps = port_info["poll_stats"]["tx_bytes"] * conv
            max_link_traffic = port_speed * self.util_thresh

            # If this is a new link, move tx_bytes of traffic on the link
            if node not in old_path:
                total_bps += tx_bps
            else:
                # FIXME TODO: DISABLED CHECK OF NON UNIQUE LINKS AS
                # UNIT-TEST FAILS, NEED TO WORK OUT WHAT CHANGES AND HOW
                # IT CHANGES.
                continue

            # Calcuate the spare of the max capacity (te threshold) and
            # spare of the total links capacity (100% usage)
            spare_of_max_traff = max_link_traffic - total_bps
            spare_of_cap = port_speed - total_bps

            # Check if a new max_usage was detected
            # Check if we found a new max usage on the path (min spare cap)
            if min_spare is None or spare_of_max_traff < min_spare[0]:
                min_spare = (spare_of_max_traff, spare_of_cap)

        # Return the max link usage (minspare cap) when swapping
        return min_spare

    def _check_already_avoids_link(self, g, paths, con_link, con_link_data):
        """ Check if any src-dest paths from `con_link_data` already avoid
        using the congested link `con_link`. If candidate avoids the link
        remove it from the candidate list and reduce congestion rate.

        Args:
            g (Graph): Topology of the network
            paths (dict): Installed source-destination path information
            con_link (tuple): Congested link in format (sw, port)
            con_link_data (dict): Congested link info with candidates and usages
        """
        new_candidates = []
        for i in range(len(con_link_data["paths"])):
            candidate, candidate_u = con_link_data["paths"][i]
            candidate_info = paths[candidate]
            candidate_path = group_table_to_path(candidate_info, g, candidate_info["ingress"])
            if self._path_avoids_link(candidate_path, con_link):
                self.logger.info("\tPath %s-%s already avoids congested port (sw: %s, pn: %s)!" %
                                    (candidate[0], candidate[1], con_link[0], con_link[1]))
                con_link_data["traffic_bps"] -= candidate_u
            else:
                new_candidates.append((candidate, candidate_u))

        # Update the list of candidates
        con_link_data["paths"] = new_candidates


# ----- STATIC METHODS -----


def CSPFPrune(g_tmp, con_link, c_path, c_bps, logger, te_thresh=0,
                        poll_rate=1, te_thresh_method=None, paccept=False):
    """ Prune a topology object (`g_tmp`) of a congested link `con_link` and
    links which do not have suffcient spare capacity to carry `c_bps` of
    candidate traffic without causing new congestion. If partial solutions
    are acceptable `paccept`, only remove links if moving the candidate
    traffic to them will cause congestion loss, otherwise a link is pruned if
    the new capacity is over the specified `te_thresh`. If a
    `te_thresh_method` is provided, threshold will be retrieved by calling
    the method with the current link details (sw and port). The method will
    not prune virtual (invalid) ports (see ``__is_port_valid``). The method
    also does not prune ports that have a virtual destination (negative
    destination port number).

    The poll_rate is used to calculate the port's current average poll
    traffic in bits.

    Args:
        g_tmp (Graph): Topology to prune of unsuitable links
        con_link (tuple): Congested link to remove from topo (sw, port)
        c_path (list of obj): Candidate path. Used to find new potential
            links (move candidate traffic to).
        c_bps (float): Candidate traffic in bps.
        logger (Logger): Logger instance used for debug info and error msg.
        te_thresh (int): Optional, can use n% of a link's total capacity.
        poll_rate (int): Poll rate in seconds used to figure out average
            traffic per second on ports.
        te_thresh_method (obj): Get threshold by calling method with current
            port details (switch ID and port number). Overrides `te_thresh`.
        paccept (bool): Accept partial solutions (default to False, no).
    """
    # Prune topology of congested links
    con_pinfo = g_tmp.get_port_info(con_link[0], con_link[1])
    if (not g_tmp.remove_port(con_link[0], con_pinfo["dest"],
                                con_link[1], con_pinfo["destPort"])):
        logger.critical("\tCan't prune topo of con port %s %s" %
                                            (con_link[0], con_link[1]))

    # Remove links that do not have sufficient headroom to carry candidate
    # traffic (if partial solutions are accepted, only remove if moving
    # candidate to link will cause congestion loss).
    rem = []
    for sw_id,sw_ports in g_tmp.topo.items():
        for src_port,port_info in sw_ports.items():
            # Check if port is valid (prunable. Ignore any links leading to
            # a virtual port (virtual dest port)
            if not __is_port_valid(g_tmp, sw_id, src_port, port_info, logger,
                                                check_virtual_dst_port=True):
                continue

            # Get the threshold for the current node using the method (if
            # provided), otherwise use the argument value
            if te_thresh_method is not None:
                te_thresh = te_thresh_method(sw_id, src_port)

            conv = 8.0 / poll_rate
            total_bps = port_info["poll_stats"]["tx_bytes"] * conv
            max_link_traffic = port_info["speed"] * te_thresh

            if paccept:
                max_link_traffic = port_info["speed"]

            # If this is a unique link add candidate traffic to total
            if __path_avoids_link(c_path, (sw_id, src_port)):
                total_bps += c_bps

            # If link does not have avaible spare capacity prune it
            if total_bps > max_link_traffic:
                logger.info("\tCan't use sw %s pn %s, pruning!" %
                                                    (sw_id, src_port))
                if (not g_tmp.remove_port(sw_id, port_info["dest"],
                                    src_port, port_info["destPort"])):
                    logger.critical("\tCan't prune topo of link sw %s pn %s" %
                                                            (sw_id, src_port))

def __path_avoids_link(path, link):
    """ Check if `path` does not contains `link`.

    Args:
        path (list): Path as list of (from_sw, to_sw, out_port)
            or (sw, in_port, out_port). Only first and last element compared.
        link (tuple): Link to check in format (sw, port)

    Returns:
        bool: False if `path` contains `link, or True otherwise.
    """
    for p in path:
        if p[0] == link[0] and p[2] == link[1]:
            return False
    return True

def __is_port_valid(g, sw, port, port_info, logger,
                                            check_virtual_dst_port=False):
    """ Check if a port is valid. A port is valid if it's not virtual
    (neative `port` number), or leads to a null destination node. If the
    `check_virtual_dst_port` flag is set, a port is also invalid if it leads
    to a virtual destination port (this is a link that leads to a host).

    Args:
        sw (obj): Source node of the port/link
        port (int): Port number (source of link)
        logger (Logger): Logger instance to output debug info
        check_virtual_dst_port (bool): Flag which indicates if method checks
            if the destination port is a virtual port. Defaults false.
    """
    # If this port has a unkown destination or its a virtual port (negative
    # port number) ignore it
    if port < 0 or port_info["dest"] is None:
        return False

    # If ignore virtual destination port is true, if the ports leads to a
    # virtual port, ignore it
    if check_virtual_dst_port and port_info["destPort"] < 0:
        return False

    # If there is no capacity/speed for port, skip
    if "speed" not in port_info:
        logger.critical("Port (%s, %s) has no speed!" % (sw, port))
        return False

    # If there are no poll stats add a default value
    if "poll_stats" not in port_info:
        logger.info("Port (%s, %s) has no poll stats, init 0" % (sw, port))
        port_info["poll_stats"] = {"tx_bytes": 0}

    # Port is valid and default stats init if applicable
    return True

def update_link_traffic(g, old_path, new_path, tx_bytes, logger):
    """ Update the topology `g` to move `tx_bytes` of traffic from `old_path`
    to `new_path`. Method will decrease the tx send rate of non-virtual links
    in the old path and increase the send rate of non-virtual links unique
    in the new path. Method ignores invalid (virtual) ports (see
    ``__is_port_valid`` for criteria). If a port does not have a stats field,
    the ``__is_port_valid`` method will initiate it to 0. If the old path
    tx_bytes poll stats field is less than the candidate traffic `tx_bytes`,
    the stats of the port will not be modified and an error is logged (
    prevent negative stats).

    NOTE: Paths can either use the (sw, in_port, out_port) format or the
    (sw, sw_to, out_port) format generated by the group table to path method.
    It's important that both `old_path` and `new_path` use the same encoding
    format.

    Args:
        g (Graph): Topology object to update link traffic for
        old_path (list of tupple): Old path as list of triples
        new_path (list of tupple): New path as list of triples
        tx_bytes (int): Number of bytes to move to the new path
        logger (Logger): Logger instance to use to show debug info
    """
    logger.info("Update traffic (%s) -> (%s)" % (old_path, new_path))

    # Remove candidate traffic from links in old path no longer in use
    for node in old_path:
        if node not in new_path and not node[2] < 0:
            port_info = g.get_port_info(node[0], node[2])
            # Check if the port is valid (not a virtual port)
            if not __is_port_valid(g, node[0], node[2], port_info, logger):
                continue

            # If poll stats is less than amount we are removing, we have
            # do not change traffic (something is wrong).
            if port_info["poll_stats"]["tx_bytes"] < tx_bytes:
                logger.critical("Moving traffic from %s %s will result in"
                            " negative stat (ORIG: %s | Bps: %s)" % (
                                node[0], node[2],
                                port_info["poll_stats"]["tx_bytes"],
                                tx_bytes
                            ))

                # XXX: MAKE STATS 0
                port_info["poll_stats"]["tx_bytes"] -= 0
                continue

            logger.info("Moved traff from %s %s (ORIG: %s | Bps: %s)" %
                    (node[0], node[2], port_info["poll_stats"]["tx_bytes"],
                    tx_bytes))
            port_info["poll_stats"]["tx_bytes"] -= tx_bytes

    # Move candidate traffic to new links in the old path
    for node in new_path:
        if node not in old_path and not node[2] < 0:
            port_info = g.get_port_info(node[0], node[2])
            # Check if the port is valid (not a virtual port)
            if not __is_port_valid(g, node[0], node[2], port_info, logger):
                continue

            logger.info("Moved traff to %s %s (ORIG: %s | Bps: %s)" %
                    (node[0], node[2], port_info["poll_stats"]["tx_bytes"],
                    tx_bytes))
            port_info["poll_stats"]["tx_bytes"] += tx_bytes

def find_solset_min_spare_capacity(g, solset, logger, te_thresh=0,
                                        poll_rate=1, te_thresh_method=None):
    """ Go through a set of potential path modifications and work out the
    new minimum spare capacity (max usage) on new candidate path links
    which were not used before. Method works similar to
    ```_swap_utilisation```, however, topology `g` needs to have the
    candidate traffic already applied to the new links. Method will ignore
    invalid (virtual) ports (see ``__is_port_valid`` for criteria).

    Paths in `solset` can either use the (sw, in_port, out_port) format or
    the (sw, sw_to, out_port) format generated by the group table to path
    method. It's important that both old and new use the same encoding
    format.

    Args:
        g (Graph): Topology object with updated candidate traffic
        solset (list): Potential path changes encoded as list of tuple
            where the first three elements of the tuple needs to be
            the candidate key, old path and new path. Paths are encoded
            as a list of triples. Other elements of the tuple are ignored.
        logger (Logger): Logger instance used for debug info and error msg.
        te_thresh (int): Optional, can use n% of a link's total capacity.
        poll_rate (int): Poll rate in seconds used to figure out average
            traffic per second on a port.
        te_thresh_method (obj): Get threshold by calling method with current
            port details (switch ID and port number). Overrides `te_thresh`.

    Returns:
        (float, float): Packed minimum spare capacity of new links used by
            the potential path where the first entry represents the spare
            capacity of link's up to the TE threshold and the second of
            the complete link speed. A negative min spare of the te
            threshold represents that traffic goes over the threshold.
    """
    min_spare = None
    for mod in solset:
        candidate = mod[0]
        old_path = mod[1]
        new_path = mod[2]
        for node in new_path:
            # If this is not a unique link, skip
            if node in old_path:
                continue

            # Get the information of the port and check if everything is there
            port_info = g.get_port_info(node[0], node[2])
            # Check if the port is valid (not a virtual port)
            if not __is_port_valid(g, node[0], node[2], port_info, logger):
                continue

            # Get the threshold for the current node using the method
            # (if provided), otherwise use the argument value
            if te_thresh_method is not None:
                te_thresh = te_thresh_method(node[0], node[2])

            # Get the current traffic on the port and compute port info
            conv = 8.0 / poll_rate
            total_bps = port_info["poll_stats"]["tx_bytes"] * conv
            max_link_traffic = port_info["speed"] * te_thresh

            # Calcuate the spare of the max capacity (te threshold) and
            # spare of the total links capacity (100% usage)
            spare_of_max_traff = max_link_traffic -total_bps
            spare_of_cap = port_info["speed"] - total_bps

            # Check if we found a new max usage on the path (min spare cap)
            if min_spare is None or spare_of_max_traff < min_spare[0]:
                min_spare = (spare_of_max_traff, spare_of_cap)
                logger.info(node)
                logger.info(max_link_traffic)

    # Return the minimum spare capacity (new maximum link usage)
    return min_spare
