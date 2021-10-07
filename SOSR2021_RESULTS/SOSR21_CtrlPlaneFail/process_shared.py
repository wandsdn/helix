#!/user/bin/python3

import statistics
from math import sqrt

""" Method that computes the confidence interval based on a list of values
(population). Infornmation will be printed on screen. If `data_list` is empty,
the method will not compute or print any information.
"""
def compute_CI (data_list):
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
    print("----")
    print("AVG: %f | N: %s" % (AVG, N))
    print("CI: %f | CI%% %f" % (CI, CI_PCENT))
    print("CI RANGE: %f to %f" % (CI_LO, CI_HI))
    print("----")


""" Update a running sum of a time difference field for a particular event
defined by `key`. If the dictionary `target` does not contain the `key` and
count field, they are added automatically. Every call of the method will
add the current `tdiff` to the running `key` value and increment the
count field.
"""
def total_time_diff (target, key, tdiff):
    key_count = key + "_count"
    if key not in target:
        target[key] = 0.0
        target[key_count] = 0

    target[key] += tdiff
    target[key_count] += 1

""" Update a field maintaing the largest seen time (larger number) as its
value. If the dictionary `target` does not contain the `key` field, the
method will automatically add the key and set its value to the current
time `t`.
"""
def largest_time (target, key, t):
    if key not in target or target[key] is None:
        target[key] = t
    elif target[key] < t:
        # Current field time is smaller than provided time so update
        target[key] = t

""" Similar to ``largest_time`` but keeps the smallest seen time as
the fields values.
"""
def smallest_time (target, key, t):
    if key not in target or target[key] is None:
        target[key] = t
    elif target[key] > t:
        # Current field time is larger than provided time so update
        target[key] = t

""" Add time `t` to a list of times in `target` using `key`. If `target`
does not contain the key `key` field, the method will automatically
add `key` to `target` and initiation it as an empty array.
"""
def list_add_time (target, key, t):
    if key not in target:
        target[key] = []
    target[key].append(t)
