#!/usr/bin/python3

import sys
import statistics
from math import sqrt

def compute_CI(data_list):
    if len(data_list) == 0:
        return

    AVG = statistics.mean(data_list)
    STDEV = statistics.stdev(data_list, AVG)
    N = len(data_list)
    Z = 1.96
    CI = Z * (STDEV / sqrt(N))
    CI_LO = AVG - CI
    CI_HI = AVG + CI
    CI_PCENT = ((CI / AVG) * 100)
#    print("AVG: %f | N: %s" % (AVG, N))
#    print("CI: %f | CI%% %f" % (CI, CI_PCENT))
#    print("CI RANGE: %f to %f" % (CI_LO, CI_HI))
    print("%f,%s,%f,%f,%f,%f" % (AVG, N, CI, CI_PCENT, CI_LO, CI_HI))


if __name__ == "__main__":
    data = []

    with open(sys.argv[1]) as fin:
        for line in fin:
            line = line.strip()
            tok = line.split(",")
            rec_time = float(tok[0])
            data.append(rec_time)

    compute_CI(data)
