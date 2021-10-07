#!/usr/bin/python3


# -----------------------------------------------------------------------------
# Process scenario 1 stage 1, compute CI info for all submetrics
# Iterate through a control-plane failure result experiment file to find any
# validation errors in the output. The script will search for the keywords
# "VALIDATION ERROR". If found, the script specifies the iteration number and
# stage the validation was encountered.
#
# NOTE: The run and stage numbers start at 0, i.e. the first stage of the first
# run is stage 0 of run 0 and the second stage of the second run is stage 1 of
# run 1.
# -----------------------------------------------------------------------------


import sys


if __name__ == "__main__":
    # Current run and scen being processed
    run = -1
    scen = 99999999

    # Did we find and pass the first list of actions of the framework output?
    found_first = False

    # Did we find a validation error that needs to be processed. If yes
    # wait for the actuall data before consuming the error (write the stage and
    # iteration to the console).
    found_error = False

    with open(sys.argv[1]) as fin:
        for line in fin:
            line = line.strip()

            # Check for the validation error line
            if "validation error" in line.lower():
                found_error = True
                continue

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
                scen = tmp_scen
                found_first = False

            if found_first and scen == 0:
                if found_error:
                    # Consume the validation error
                    print("Found validation error during run %s stage %s" %
                                                                (run, scen))
                    found_error = False
