#!/usr/bin/python3



import sys
from argparse import ArgumentParser


def in_range(ranges, value):
    """ Check if `value` is betweny a range defined by `ranges`.

    Returns:
        bool: True if `value` in a range of `ranges`, false otherwise.
    """
    for r in ranges:
        if value >= r["start"] and value <= r["end"]:
            return True
    return False


if __name__ == "__main__":
    parser = ArgumentParser("Emulate Ctrl Fail Result Processor")
    parser.add_argument("--file", required=True, type=str,
        help="File to filter through")
    parser.add_argument("--run", required=False, type=int,
        help="Print results for iteration r")
    parser.add_argument("--multi", metavar="r1:r2", type=str, nargs="+",
        help="Prin results for iteratuin range r1 to r2 (inclusive)")
    parser.add_argument("--stage", required=False, type=int,
        help="Only print results for stage i (applies to both filter types)")
    args = parser.parse_args()

    # Make sure run number is specified (otherwise print error and exit)
    if args.run is None and args.multi is None:
        print("Please provide either a run or stage number")
        exit(0)

    # Process the single or multi run argument into a list of ranges
    run_range = []
    if args.run is not None:
        run_range.append({"start": args.run, "end": args.run})

    if args.multi is not None:
        for tmp in args.multi:
            if ":" not in tmp:
                print("Invalid multi line argument format: %s" % tmp)
                continue
            tok = tmp.split(":")
            start = int(tok[0])
            end = int(tok[1])
            run_range.append({"start": start, "end": end})

    # Current run and scen being processed
    run = -1
    scen = 99999999
    skip_valid_err = 0

    with open(args.file) as fin:
        for line in fin:
            line = line.strip()

            # Ignore empty lines
            if line == "":
                continue

            # Ingore the validation error output
            if "!!" in line:
                skip_valid_err = 3
                continue
            if skip_valid_err > 0:
                skip_valid_err -= 1
                continue

            # Tokenize the line
            tok = line.split(",")

            # Get the scenario and compare
            try:
                tmp_scen = int(tok[0])
            except ValueError as e:
                # If line has no scenario process as the current scenario
                tmp_scen = scen

            if tmp_scen != scen:
                # Scenario wrapped, this is data for the next run
                if tmp_scen < scen:
                    run += 1
                scen = tmp_scen

            if in_range(run_range, run):
                if args.stage is None or args.stage == scen:
                    print(line)
