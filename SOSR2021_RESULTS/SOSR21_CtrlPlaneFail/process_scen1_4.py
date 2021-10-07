#!/usr/bin/python3


# -----------------------------------------------------------------------------
# Process scenario 1 stage 4, compute CI info for all submetrics
#
# [x] = Time of event
# LE: Local Event | OF: Control-Channel Event (OpenFlow)
#
# GENERATED METRICS (TIME)
#   Root Dead IDP Detect: [Last LE Root Dead IDP]* - [Last Fail Action]
#   Root Compute Path: [Last LE Root Dead IDP]* - [First LE Root Compute Path]*
#   LCs Path Install: [Last OF Group Mod] - [First LE Root Compute Path]*
#   Root Dead IDP Detect: [Last LE Root Dead IDP] - [Last Fail Action]
#   Root Compute Path 2: [Last LE Root Compute Path] - [Last LE Root Dead IDP]
#
#   Stage Time (Actual Recovery): [Last OF Group Mod] - [Last Fail Action]
#   Stage Time: [Last Timeline Entry] - [First Timeline Entry]
#
#   * = [Last LE Root Dead IDP] and [First LE Root Compute Path] refer to the
#   last and first root controller event which triggered the inter-domain path
#   instalation event on the other domains. Because we are dealing with multi
#   controllers, dead IDP detection may be staggered meaning that only some
#   of the events (not up to the last event) will trigger the root controller
#   to recompute the paths. This is more of a behaivour due to the topology
#   used for the scenario as a single failure on the inter-domain links will
#   fully disconnet the path. Regarldess, even if more links are avaible,
#   you will still get an early recomputation and re-installation.
#
#   THIS SCRIPT REPORTS THE TIME RELEVANT TO THE RECOMPUTATION/INSTALL !!!
# -----------------------------------------------------------------------------


import sys
from process_shared import compute_CI
from process_shared import largest_time, smallest_time


if __name__ == "__main__":
    data = {}

    # Current run and scen being processed
    run = -1
    scen = 99999999

    # Did we find and pass the first list of actions of the framework output?
    found_first = False

    with open(sys.argv[1]) as fin:
        for line in fin:
            line = line.strip()
            tok = line.split(",")
            if len(tok) == 1 and tok[0] == "-----":
                if found_first == False:
                    found_first = True
                continue

            # Get the scenario and compare
            try:
                tmp_scen = int(tok[0])
            except ValueError as e:
                # Skip lines with invalid scenarios (i.e. first token is not a
                # number)
                continue

            if tmp_scen != scen:
                # Scenario wrapped, this is data for the next run
                if tmp_scen < scen:
                    run += 1
                    data[run] = {"stage_start": None, "stage_end": None}
                scen = tmp_scen
                found_first = False

            if found_first and scen == 3:
                # Extract the fields of the line
                cid = tok[1]
                cid = cid.split(".")[0]
                time = float(tok[2])
                tdiff = float(tok[3])
                ev_type = tok[4]
                ev_info = tok[5]
                ev_ext = None
                if len(tok) > 6:
                    ev_ext = tok[6]

                # Deal with the field duplication error
                if ev_type == ev_info:
                    ev_info = tok[6]
                    if len(tok) > 7:
                        ev_ext = tok[7]

                # Update stage start and time accordingly
                smallest_time(data[run], "stage_start", time)
                largest_time(data[run], "stage_end", time)

                if ev_type == "action" and ev_info == "fail" and ev_ext == "c2":
                    cid = "root"
                    if cid not in data[run]:
                        data[run][cid] = {}
                    largest_time(data[run][cid], "fail_action", time)
                elif ev_type == "event_local":
                    if ev_info == "dead_idp":
                        if cid not in data[run]:
                            data[run][cid] = {}
                        if "dead_idp" not in data[run][cid]:
                            data[run][cid]["dead_idp"] = []
                        data[run][cid]["dead_idp"].append(time)
                    elif ev_info == "comp_path":
                        if cid not in data[run]:
                            data[run][cid] = {}
                        if "comp_path" not in data[run][cid]:
                            data[run][cid]["comp_path"] = []
                        data[run][cid]["comp_path"].append(time)
                    elif ev_info == "dead_ctrl" and ev_ext == "1002":
                        if cid not in data[run]:
                            data[run][cid] = {}
                        largest_time(data[run][cid], "dead_ctrl", time)
                elif ev_type == "event_ofp":
                    if ev_info == "group_mod" and ev_ext == "True":
                        cid = "root"
                        if cid not in data[run]:
                            data[run][cid] = {}
                        largest_time(data[run][cid], "comp_path_inst", time)


    # XXX: Go through the list of root path computations and dead IDP time
    # arrays to find events which triggered the path instalation.
    for run, run_d in data.items():
        cid_d = run_d["root"]
        for i in range(len(cid_d["comp_path"])-1, -1, -1):
            if cid_d["comp_path"][i] < cid_d["comp_path_inst"]:
                cid_d["cp_before_inst"] = cid_d["comp_path"][i]
                break

        if "cp_before_inst" in cid_d:
            for i in range(len(cid_d["dead_idp"])-1, -1, -1):
                if cid_d["dead_idp"][i] < cid_d["cp_before_inst"]:
                    cid_d["didp_before_inst"] = cid_d["dead_idp"][i]
                    break

    # Process the root failure detection time
    print("\nFAILURE DETECTION IDP")
    print("run,Value,Fail Action Time,Last Dead IDP Time")
    dat_list = []
    for run, run_d in data.items():
        if "root" not in run_d:
            print("MISSING ROOT INFORMATION: RUN %s" % run)
            continue

        cid_d = run_d["root"]
        if "fail_action" not in cid_d or "didp_before_inst" not in cid_d:
            print("MISSING FIELDS: RUN %s" % run)
            continue

        diff = cid_d["didp_before_inst"] - cid_d["fail_action"]
        dat_list.append(diff)
        print("%s,%s,%s,%s" % (run, diff, cid_d["fail_action"],
                                cid_d["didp_before_inst"]))

    compute_CI(dat_list)


    # Process the root path compute after the IDP
    print("\nROOT COMPUTE PATH AFTER IDP")
    print("run,Value,Last Dead IDP Time,First Root Compute Path Time")
    dat_list = []
    for run, run_d in data.items():
        if "root" not in run_d:
            print("MISSING ROOT INFORMATION: RUN %s" % run)
            continue

        cid_d = run_d["root"]
        if "didp_before_inst" not in cid_d or "cp_before_inst" not in cid_d:
            print("MISSING FIELDS: RUN %s" % run)
            continue

        diff = cid_d["cp_before_inst"] - cid_d["didp_before_inst"]
        dat_list.append(diff)
        print("%s,%s,%s,%s" % (run, diff, cid_d["didp_before_inst"],
                            cid_d["cp_before_inst"]))

    compute_CI(dat_list)


    # Process the root path instalation
    print("\nROOT PATH INSTALATION")
    print("run,Value,First Root Comp Path Time,Last Path Install Time")
    dat_list = []
    for run, run_d in data.items():
        if "root" not in run_d:
            print("MISSING ROOT INFORMATION: RUN %s" % run)
            continue

        cid_d = run_d["root"]
        if "cp_before_inst" not in cid_d or "comp_path_inst" not in cid_d:
            print("MISSING FIELDS: RUN %s" % run)
            continue

        diff = cid_d["comp_path_inst"] - cid_d["cp_before_inst"]
        dat_list.append(diff)
        print("%s,%s,%s,%s" % (run, diff, cid_d["cp_before_inst"],
                                    cid_d["comp_path_inst"]))

    compute_CI(dat_list)


    # Process the dead domain of the root controller
    print("\nROOT DEAD DOMAIN (From Start)")
    print("run,Value,Failure Action Time,Dead Ctrl Detect Time")
    dat_list = []
    for run, run_d in data.items():
        if "root" not in run_d:
            print("MISSING ROOT INFORMATION: RUN %s" % run)
            continue

        cid_d = run_d["root"]
        if "fail_action" not in cid_d or "dead_ctrl" not in cid_d:
            print("MISSING FIELDS: RUN %s" % run)
            continue

        diff = cid_d["dead_ctrl"] - cid_d["fail_action"]
        dat_list.append(diff)
        print("%s,%s,%s,%s" % (run, diff, cid_d["fail_action"],
                                cid_d["dead_ctrl"]))

    compute_CI(dat_list)


    # Process the root path compute after the IDP
    print("\nROOT COMPUTE PATH AFTER DEAD DOMAIN")
    print("run,Value,Dead Ctrl Detect Time, Last Root Compute Path")
    dat_list = []
    for run, run_d in data.items():
        if "root" not in run_d:
            print("MISSING ROOT INFORMATION: RUN %s" % run)
            continue

        cid_d = run_d["root"]
        if "dead_ctrl" not in cid_d or "comp_path" not in cid_d:
            print("MISSING FIELDS: RUN %s" % run)
            continue

        diff = cid_d["comp_path"][-1] - cid_d["dead_ctrl"]
        dat_list.append(diff)
        print("%s,%s,%s,%s" % (run, diff, cid_d["dead_ctrl"],
                                cid_d["comp_path"][-1]))

    compute_CI(dat_list)


    # Process the stage time prime data
    print("\nSTAGE TIME (ACTUAL RECOVERY)")
    print("run,Value,Last Fail Action Time,Last Path Install Time")
    dat_list = []
    for run, run_d in data.items():
        if "root" not in run_d:
            print("MISSING ROOT INFORMATION: RUN %s" % run)
            continue

        cid_d = run_d["root"]
        if "fail_action" not in cid_d or "comp_path_inst" not in cid_d:
            print("MISSING FIELDS: RUN %s" % run)
            continue

        diff = cid_d["comp_path_inst"] - cid_d["fail_action"]
        dat_list.append(diff)
        print("%s,%s,%s,%s" % (run, diff, cid_d["fail_action"],
                                cid_d["comp_path_inst"]))

    compute_CI(dat_list)


    # Process the stage time data
    print("\nSTAGE TIME")
    print("run,Value,Stage Start Time,Stage End Time")
    dat_list = []
    for run, run_d in data.items():
        if run_d["stage_end"] is None or run_d["stage_start"] is None:
            print("MISSING STAGE DATA: RUN %s" % run)
            continue

        diff = run_d["stage_end"] - run_d["stage_start"]
        dat_list.append(diff)
        print("%s,%s,%s,%s" % (run, diff, run_d["stage_start"], run_d["stage_end"]))

    compute_CI(dat_list)
