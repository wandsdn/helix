#/bin/bash

# ---------------------------------------------------------------
# Runner script that executes the topology test 100 times, saving
# the results into a csv file. Please note that this script has
# to be run as root !!!
# ---------------------------------------------------------------

# Number of tests to run for each scenario
NUM_TESTS=100


# ---------- 20 MS RTT ----------
mkdir ResLinkFail_20ms;

# Control channel options to use for the experiment (20ms RTT)
CTRL_OPT="delay 10ms"
# Declare the array of controllers to use
declare -a CONTROLLERS=("reactive" "proactive" "proactive_alt")
# Declare the array of networks to use
declare -a NETWORKS=("TestNet" "ExtendedTestNet" "TestPathSpliceFixNet" "FatTreeNet")
# Declare an array of failure scenarios to run
declare -a FAILURES=("fail_1" "fail_2" "fail_3" "fail_4" "fail_5" "fail_6")
for network in "${NETWORKS[@]}";
do
    for controller in "${CONTROLLERS[@]}";
    do
        for failure in "${FAILURES[@]}";
        do
            fname="ResLinkFail_20ms/stat.$network.$controller.$failure.csv"
            echo "Clearing file $fname";
            echo -ne "" > $fname;

            echo "Starting tests ...";
            for i in `seq 1 $NUM_TESTS`;
            do
                echo "Running test $i of $NUM_TESTS"
                `./EmulateLinkFailure.py --topo "Networks.$network" --controller \
                    "$controller" --failure "Scenario_LinkFail/$failure.yaml" \
                    --ctrl_options "$CTRL_OPT" >> "$fname" 2>&1`
            done

            lines=`cat "$fname" | wc -l`
            if [[ $lines -eq 0 ]];
            then
                echo "Removing empty stat file $fname"
                rm $fname
            fi
        done
    done
done

# ---------- 4 MS RTT ----------
mkdir ResLinkFail_4ms;

# Control channel options to use for the experiment (20ms RTT)
CTRL_OPT="delay 10ms"
# Declare the array of controllers to use
declare -a CONTROLLERS=("reactive" "proactive" "proactive_alt")
# Declare the array of networks to use
declare -a NETWORKS=("TestNet" "ExtendedTestNet" "TestPathSpliceFixNet" "FatTreeNet")
# Declare an array of failure scenarios to run
declare -a FAILURES=("fail_1" "fail_2" "fail_3" "fail_4" "fail_5" "fail_6")
for network in "${NETWORKS[@]}";
do
    for controller in "${CONTROLLERS[@]}";
    do
        for failure in "${FAILURES[@]}";
        do
            fname="ResLinkFail_4ms/stat.$network.$controller.$failure.csv"
            echo "Clearing file $fname";
            echo -ne "" > $fname;

            echo "Starting tests ...";
            for i in `seq 1 $NUM_TESTS`;
            do
                echo "Running test $i of $NUM_TESTS"
                `./EmulateLinkFailure.py --topo "Networks.$network" --controller \
                    "$controller" --failure "Scenario_LinkFail/$failure.yaml" \
                    --ctrl_options "$CTRL_OPT" >> "$fname" 2>&1`
            done

            lines=`cat "$fname" | wc -l`
            if [[ $lines -eq 0 ]];
            then
                echo "Removing empty stat file $fname"
                rm $fname
            fi
        done
    done
done
