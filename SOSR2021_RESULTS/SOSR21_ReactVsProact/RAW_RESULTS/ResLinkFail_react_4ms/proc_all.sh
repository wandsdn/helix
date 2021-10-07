#!/bin/bash

CONTROLLERS=("reactive4ms")

echo "Topo,Controller,Failure,AVG,N,CI95,CI%,RangeLower,RangeUpper"

# Test Net Topology Process
FAILURES=("fail_1" "fail_2" "fail_3")
for ctrl in "${CONTROLLERS[@]}";
do
    for f in "${FAILURES[@]}";
    do
        file="stat.TestNet.$ctrl.$f.csv";
        info=`python3 ../proc_avg.py $file`;
        echo "TN,$ctrl,$f,$info";
    done
done

# Extended Test Net Topology Process
FAILURES=("fail_4" "fail_5")
for ctrl in "${CONTROLLERS[@]}";
do
    for f in "${FAILURES[@]}";
    do
        file="stat.ExtendedTestNet.$ctrl.$f.csv";
        info=`python3 ../proc_avg.py $file`;
        echo "ETN,$ctrl,$f,$info";
    done
done

# Test Path Splice Fix Net Topology Process
FAILURES=("fail_4" "fail_5")
for ctrl in "${CONTROLLERS[@]}";
do
    for f in "${FAILURES[@]}";
    do
        file="stat.TestPathSpliceFixNet.$ctrl.$f.csv";
        info=`python3 ../proc_avg.py $file`;
        echo "TPSFN,$ctrl,$f,$info";
    done
done

# Fat Tree Net Topology Process
FAILURES=("fail_6")
for ctrl in "${CONTROLLERS[@]}";
do
    for f in "${FAILURES[@]}";
    do
        file="stat.FatTreeNet.$ctrl.$f.csv";
        info=`python3 ../proc_avg.py $file`;
        echo "FTN,$ctrl,$f,$info";
    done
done
