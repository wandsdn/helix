#!/usr/bin/python3


# -----------------------------------------------------------------------------
# Process scenario 1 stage 5, compute CI info for all submetrics
#
# [x] = Time of event
# LE: Local Event | OF: Control-Channel Event (OpenFlow)
#
# GENERATED METRICS (TIME)
#   c2 Instance Start: [Last LE Send Find] - [Last Start Action]
#   c2 Instance Init Phase: [Last LE Role Change] - [Last LE Send Find]
#   c2 SW Enter: [Last Last SW Enter] - [Last LE Send Find]
#   c2 Role Change: [Last OF Role Change Req] - [Last SW Enter]
#                       | OR IF (SW Enter) done before (Init Phase End)
#                   [LAST OF Role Change Req] - [Last LE Role Change]
#   Root Compute Path: [Last LE Root Compute Path] - [Last Start Action]
#   c2 Install Path: [Last LE Root Compute Path] - [Last OF Group Mod]
#
#   Stage Time: [Last Timeline Entry] - [First Timeline Entry]
#
#   XXXNOTE: C2 role change time is calcualted from either the last switch
#   enter event or init end event (same as scenario 1 stage 2).
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
            tmp_scen = int(tok[0])
            if tmp_scen != scen:
                # Scenario wrapped, this is data for the next run
                if tmp_scen < scen:
                    run += 1
                    data[run] = {"stage_start": None, "stage_end": None}
                scen = tmp_scen
                found_first = False

            if found_first and scen == 4:
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

                if ev_type == "action" and ev_info == "start" and ev_ext == "c2.1":
                    if cid not in data[run]:
                        data[run][cid] = {}
                    largest_time(data[run][cid], "start_action", time)
                elif ev_type == "event_local":
                    if cid == "c2" and ev_info == "send_find":
                        if cid not in data[run]:
                            data[run][cid] = {}
                        largest_time(data[run][cid], "send_find", time)
                    elif cid == "c2" and ev_info == "role" and ev_ext == "master":
                        if cid not in data[run]:
                            data[run][cid] = {}
                        largest_time(data[run][cid], "init_end", time)
                    elif cid == "c2" and ev_info == "sw_enter":
                        if cid not in data[run]:
                            data[run][cid] = {}
                        largest_time(data[run][cid], "sw_enter", time)
                    elif cid == "root" and ev_info == "comp_path":
                        if cid not in data[run]:
                            data[run][cid] = {}
                        largest_time(data[run][cid], "comp_path", time)
                elif ev_type == "event_ofp":
                    if ev_info == "role_change" and ev_ext == "master":
                        if cid not in data[run]:
                            data[run][cid] = {}
                        largest_time(data[run][cid], "role_change", time)
                    if ev_info == "group_mod" and ev_ext == "True":
                        cid = "root"
                        if cid not in data[run]:
                            data[run][cid] = {}
                        largest_time(data[run][cid], "comp_path_inst", time)


    # Process the instance start time
    print("\nINSTANCE START TIME")
    print("run,CID,Value,Start Action Time,Send Find Time")
    dat_list = []
    for run, run_d in data.items():
        for cid in sorted(run_d.keys()):
            # If the key is not for a instance skip
            if not cid.startswith("c"):
                continue

            cid_d = run_d[cid]
            if "start_action" not in cid_d or "send_find" not in cid_d:
                print("MISSING FIELDS: RUN %s CID %s" % (run, cid))
                continue
            diff = cid_d["send_find"] - cid_d["start_action"]
            dat_list.append(diff)
            print("%s,%s,%s,%s,%s" % (run, cid, diff, cid_d["start_action"],
                                        cid_d["send_find"]))

    compute_CI(dat_list)


    # Process the instance initiation phase time
    print("\nINSTANCE INIT PHASE TIME")
    print("run,CID,Value,Send Fint Time,Init End Time")
    dat_list = []
    for run, run_d in data.items():
        for cid in sorted(run_d.keys()):
            # If the key is not for a instance skip
            if not cid.startswith("c"):
                continue

            cid_d = run_d[cid]
            if "send_find" not in cid_d or "init_end" not in cid_d:
                print("MISSING FIELDS: RUN %s CID %s" % (run, cid))
                continue
            diff = cid_d["init_end"] - cid_d["send_find"]
            dat_list.append(diff)
            print("%s,%s,%s,%s,%s" % (run, cid, diff, cid_d["send_find"],
                                        cid_d["init_end"]))

    compute_CI(dat_list)


    # Process the switch enter time
    print("\nSW ENTER TIME")
    print("run,CID,Value,Send Find Time,SW Enter Time")
    dat_list = []
    for run, run_d in data.items():
        for cid in sorted(run_d.keys()):
            # If the key is not for a instance skip
            if not cid.startswith("c"):
                continue

            cid_d = run_d[cid]
            if "send_find" not in cid_d or "sw_enter" not in cid_d:
                print("MISSING FIELDS: RUN %s CID %S" % (run, cid))
                continue
            diff = cid_d["sw_enter"] - cid_d["send_find"]
            dat_list.append(diff)
            print("%s,%s,%s,%s,%s" % (run, cid, diff, cid_d["send_find"],
                                        cid_d["sw_enter"]))

    compute_CI(dat_list)


    # Process the role change data
    print("\nROLE CHANGE TIME")
    print("run,CID,Value,Init End Time,SW Enter Time,Role Change Time,Value From Init End")
    dat_list = []
    for run, run_d in data.items():
        for cid in sorted(run_d.keys()):
            # If the key is not for a instance skip
            if not cid.startswith("c"):
                continue

            cid_d = run_d[cid]
            if ("init_end" not in cid_d or "sw_enter" not in cid_d or
                                                "role_change" not in cid_d):
                print("MISSING FIELDS: RUN %s CID %s" % (run, cid))
                continue

            if cid_d["init_end"] < cid_d["sw_enter"]:
                diff = cid_d["role_change"] - cid_d["sw_enter"]
            else:
                diff = cid_d["role_change"] - cid_d["init_end"]
            dat_list.append(diff)
            diff_init_end = cid_d["role_change"] - cid_d["init_end"]
            print("%s,%s,%s,%s,%s,%s,%s" % (run, cid, diff, cid_d["init_end"],
                        cid_d["sw_enter"], cid_d["role_change"], diff_init_end))

    compute_CI(dat_list)


    # Process the root path compute
    print("\nROOT COMPUTE PATH")
    print("run,Value,Root Compute Path Time,Start Action time")
    dat_list = []
    for run, run_d in data.items():
        if "root" not in run_d:
            print("MISSING ROOT INFORMATION: RUN %s" % run)
            continue
        if "c2" not in run_d:
            print("MISSING c2 INFORMATION: RUN %s" % run)
            continue

        cid_d = run_d["root"]
        if "comp_path" not in cid_d or "start_action" not in run_d["c2"]:
            print("MISSING FIELDS: RUN %s" % run)
            continue

        diff = cid_d["comp_path"] - run_d["c2"]["start_action"]
        dat_list.append(diff)
        print("%s,%s,%s,%s" % (run, diff, cid_d["comp_path"],
                                run_d["c2"]["start_action"]))

    compute_CI(dat_list)


    # Process the root path instalation
    print("\nROOT PATH INSTALATION")
    print("run,Value,Compute Path Time,Compute Path Install Time")
    dat_list = []
    for run, run_d in data.items():
        if "root" not in run_d:
            print("MISSING ROOT INFORMATION: RUN %s" % run)
            continue

        cid_d = run_d["root"]
        if "comp_path" not in cid_d or "comp_path_inst" not in cid_d:
            print("MISSING FIELDS: RUN %s" % run)
            continue

        diff = cid_d["comp_path_inst"] - cid_d["comp_path"]
        dat_list.append(diff)
        print("%s,%s,%s,%s" % (run, diff, cid_d["comp_path"],
                                cid_d["comp_path_inst"]))

    compute_CI(dat_list)


    # Process the stage time data
    print("\nSTAGE TIME")
    print("run,Value,Stage Start Time,Stage End Time")
    dat_list = []
    for run, run_d in data.items():
        diff = run_d["stage_end"] - run_d["stage_start"]
        dat_list.append(diff)
        print("%s,%s,%s,%s" % (run, diff, run_d["stage_start"], run_d["stage_end"]))

    compute_CI(dat_list)
