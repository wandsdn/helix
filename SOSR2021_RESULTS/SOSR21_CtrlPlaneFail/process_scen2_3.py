#!/usr/bin/python3


# -----------------------------------------------------------------------------
# Process scenario 2 stage 1, compute CI info for all submetrics
#
# [x] = Time of event
# LE: Local Event | OF: Control-Channel Event (OpenFlow)
#
# GENERATED METRICS (TIME):
#   c2.1,c2.2 Instance Start: [Last LE Send Find] - [Last Start Action]
#   c2.1,c2.2 Instance Init Phase: [Last LE Role Change] - [Last LE Send Find]
#   c2.1,c2.2 SW Enter: [Last Last SW Enter] - [Last LE Send Find]
#   c2.1,c2.2 Role Change: [Last OF Role Change Req] - [Last SW Enter]
#                       | OR IF (SW Enter) done before (Init Phase End)
#                   [LAST OF Role Change Req] - [Last LE Role Change]
#
#   Stage Time: [Last Timeline Entry] - [First Timeline Entry]
# -----------------------------------------------------------------------------


import sys,pprint
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

            if found_first and scen == 2:
                # Extract the fields of the line
                cid_full = tok[1]
                if "." not in cid_full:
                    cid_full = "%s.0" % cid_full
                cid = cid_full
                #cid = cid_full.split(".")[0]
                time = float(tok[2])
                tdiff = float(tok[3])
                ev_type = tok[4]
                ev_info = tok[5]
                ev_ext = None
                if len(tok) > 6:
                    ev_ext = tok[6]

                # Update stage start and time accordingly
                smallest_time(data[run], "stage_start", time)
                largest_time(data[run], "stage_end", time)

                cid = "root.0"
                if ev_type == "action":
                    if ev_info == "fail":
                        if ev_ext == "c2" or ev_ext == "c2.1":
                            if cid not in data[run]:
                                data[run][cid] = {}
                            largest_time(data[run][cid], "fail_action_other", time)
                        else:
                            if cid not in data[run]:
                                data[run][cid] = {}
                            largest_time(data[run][cid], "fail_action", time)
                elif ev_type == "event_local":
                    if ev_info == "inst_fail":
                        if cid not in data[run]:
                            data[run][cid] = {}
                        largest_time(data[run][cid], "fail_detect", time)
                    elif ev_info == "role" and ev_ext == "master":
                        if cid not in data[run]:
                            data[run][cid] = {}
                        largest_time(data[run][cid], "role_change", time)
                    elif ev_info == "dead_idp":
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
                    if ev_info == "role_change" and ev_ext == "master":
                        if cid not in data[run]:
                            data[run][cid] = {}
                        largest_time(data[run][cid], "role_change", time)
                    if ev_info == "group_mod" and ev_ext == "True":
                        if cid not in data[run]:
                            data[run][cid] = {}
                        largest_time(data[run][cid], "comp_path_inst", time)


    # XXX: Go through the list of root path computations and dead IDP time
    # arrays to find events which triggered the path instalation.
    for run, run_d in data.items():
        if "root.0" not in run_d:
            print("MISSING root.0 INFO FOR RUN %s" % run)
            continue

        cid_d = run_d["root.0"]
        for i in range(len(cid_d["comp_path"])-1, -1, -1):
            if cid_d["comp_path"][i] < cid_d["comp_path_inst"]:
                cid_d["cp_before_inst"] = cid_d["comp_path"][i]
                break

        if "cp_before_inst" in cid_d:
            for i in range(len(cid_d["dead_idp"])-1, -1, -1):
                if cid_d["dead_idp"][i] < cid_d["cp_before_inst"]:
                    cid_d["didp_before_inst"] = cid_d["dead_idp"][i]
                    break


    # Process the failure detection time
    print("\nFAILURE DETECTION TIME")
    print("run,CID,Value,Detected Failure Of,Fail Action Time,")
    dat_list = []
    for run, run_d in data.items():
        if "root.0" not in run_d:
            print("MISSING root.0 INFO FOR RUN %s" % run)
            continue

        cid_d = run_d["root.0"]
        if "fail_action_other" not in cid_d or "fail_detect" not in cid_d:
            print("MISSING FIELDS: RUN %s CID %s" % (run, cid))
            continue

        fd_time = cid_d["fail_detect"]
        fa_time = cid_d["fail_action_other"]
        diff = fd_time - fa_time
        dat_list.append(diff)
        print("%s,%s,%s,%s,%s" % (run, cid, diff, fa_time, fd_time))

    compute_CI(dat_list)


    # Process the role change time
    print("\nROLE CHANGE TIME")
    print("run,CID,Value,Fail Detect Time, Role Change Time")
    dat_list = []
    for run, run_d in data.items():
        if "root.0" not in run_d:
            print("MISSING root.0 INFO FOR RUN %s" % run)
            continue

        cid_d = run_d["root.0"]
        if "fail_detect" not in cid_d or "role_change" not in cid_d:
            print("MISSING FIELDS: RUN %s CID %s" % (run, cid))
            continue

        fd_time = cid_d["fail_detect"]
        rc_time = cid_d["role_change"]
        diff = rc_time - fd_time
        dat_list.append(diff)
        print("%s,%s,%s,%s,%s" % (run, cid, diff, fd_time, rc_time))

    compute_CI(dat_list)


    # Process the root failure detection time
    print("\nFAILURE DETECTION IDP")
    print("run,Value,Fail Action Time,Last Dead IDP Time")
    dat_list = []
    for run, run_d in data.items():
        if "root.0" not in run_d:
            print("MISSING ROOT INFORMATION: RUN %s" % run)
            continue

        cid_d = run_d["root.0"]
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
        if "root.0" not in run_d:
            print("MISSING ROOT INFORMATION: RUN %s" % run)
            continue

        cid_d = run_d["root.0"]
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
        if "root.0" not in run_d:
            print("MISSING ROOT INFORMATION: RUN %s" % run)
            continue

        cid_d = run_d["root.0"]
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
        if "root.0" not in run_d:
            print("MISSING ROOT INFORMATION: RUN %s" % run)
            continue

        cid_d = run_d["root.0"]
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
        if "root.0" not in run_d:
            print("MISSING ROOT INFORMATION: RUN %s" % run)
            continue

        cid_d = run_d["root.0"]
        if "dead_ctrl" not in cid_d or "comp_path" not in cid_d:
            print("MISSING FIELDS: RUN %s" % run)
            continue

        diff = cid_d["comp_path"][-1] - cid_d["dead_ctrl"]
        dat_list.append(diff)
        print("%s,%s,%s,%s" % (run, diff, cid_d["dead_ctrl"],
                                cid_d["comp_path"][-1]))

    compute_CI(dat_list)


    # Process the stage time actual recovery data
    print("\nSTAGE TIME (ACTUAL RECOVERY)")
    print("run,Value,Last c2.2 Fail Action Time,Last Path Install Time")
    dat_list = []
    for run, run_d in data.items():
        if "root.0" not in run_d:
            print("MISSING ROOT INFORMATION: RUN %s" % run)
            continue

        cid_d = run_d["root.0"]
        if "fail_action" not in cid_d or "comp_path_inst" not in cid_d:
            print("MISSING FIELDS: RUN %s" % run)
            continue

        diff = cid_d["comp_path_inst"] - cid_d["fail_action"]
        dat_list.append(diff)
        print("%s,%s,%s,%s" % (run, diff, cid_d["fail_action"],
                                cid_d["comp_path_inst"]))

    compute_CI(dat_list)


    # Process the stage time from the first unreleated failure
    print("\nSTAGE TIME (FROM FIRST FAIL)")
    print("run,Value,stage Start Time,Last Path Install Time")
    dat_list = []
    for run, run_d in data.items():
        if "root.0" not in run_d:
            print("MISSING ROOT INFORMATION: RUN %s" % run)
            continue

        cid_d = run_d["root.0"]
        if run_d["stage_start"] is None or "comp_path_inst" not in cid_d:
            print("MISSING FIELDS: RUN %s" % run)
            continue

        diff = cid_d["comp_path_inst"] - run_d["stage_start"]
        dat_list.append(diff)
        print("%s,%s,%s,%s" % (run, diff, run_d["stage_start"],
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
