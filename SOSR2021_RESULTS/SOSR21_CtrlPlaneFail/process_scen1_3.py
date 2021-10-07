#!/usr/bin/python3


# -----------------------------------------------------------------------------
# Process scenario 1 stage 1, compute CI info for all submetrics
#
# [x] = Time of event
# LE: Local Event | OF: Control-Channel Event (OpenFlow)
#
# GENERATED METRICS (TIME)
#   C2 Failure Detection: [Last LE Fail Detect] - [Last Fail Action]
#   C2 Role Change: [Last OF Role Change Req] - [Last LE Fail Detect]
#
#   Stage Time: [Last Timeline Entry] - [First Timeline Entry]
# -----------------------------------------------------------------------------


import sys
from process_shared import compute_CI, total_time_diff
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
                cid = tok[1]
                cid = cid.split(".")[0]
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

                if ev_type == "action":
                    if cid not in data[run]:
                        data[run][cid] = {}
                    largest_time(data[run][cid], "fail_action", time)
                elif ev_type == "event_local":
                    if ev_info == "inst_fail" and ev_ext == "1":
                        if cid not in data[run]:
                            data[run][cid] = {}
                        largest_time(data[run][cid], "fail_detect", time)
                    elif ev_info == "role" and ev_ext == "master":
                        if cid not in data[run]:
                            data[run][cid] = {}
                        largest_time(data[run][cid], "role_change", time)
                elif ev_type == "event_ofp":
                    if ev_info == "role_change" and ev_ext == "master":
                        if cid not in data[run]:
                            data[run][cid] = {}
                        largest_time(data[run][cid], "role_change", time)

    # Process the failure detection time
    print("\nFAILURE DETECTION TIME")
    print("run,CID,Value,Fail Action Time,Fail Detect Time")
    dat_list = []
    for run, run_d in data.items():
        for cid in sorted(run_d.keys()):
            # If the key is not for a instance skip
            if not cid.startswith("c"):
                continue

            cid_d = run_d[cid]
            if "fail_action" not in cid_d or "fail_detect" not in cid_d:
                print("MISSING FIELDS: RUN %s CID %s" % (run, cid))
                continue
            diff = cid_d["fail_detect"] - cid_d["fail_action"]
            dat_list.append(diff)
            print("%s,%s,%s,%s,%s" % (run, cid, diff, cid_d["fail_action"],
                                        cid_d["fail_detect"]))

    compute_CI(dat_list)


    # Process the role change time
    print("\nROLE CHANGE TIME")
    print("run,CID,Value,Fail Detect Time,Role Change Time")
    dat_list = []
    for run, run_d in data.items():
        for cid in sorted(run_d.keys()):
            # If the key is not for a instance skip
            if not cid.startswith("c"):
                continue

            cid_d = run_d[cid]
            if "fail_detect" not in cid_d or "role_change" not in cid_d:
                print("MISSING FIELDS: RUN %s CID %s" % (run, cid))
                continue
            diff = cid_d["role_change"] - cid_d["fail_detect"]
            dat_list.append(diff)
            print("%s,%s,%s,%s,%s" % (run, cid, diff, cid_d["fail_detect"],
                                    cid_d["role_change"]))

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
