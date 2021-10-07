#!/bin/bash

# Number of times to repeat the tests
NUM_TESTS=100
# Control channel options to use for the experiments (10ms, i.e. 20ms RTT)
CTRL_OPT="delay 10ms"
# Extra emulator flags
EXTRA_FLAG="--disable_te"

# Path to topology, scenario and switch-ctrl mapping file to use for
# emulation. These variables can change for every seperate experiment
TOPO="Networks/MCTestScenario_v2.py"
SCEN="Scenario_CtrlFail/scen1.yaml"
MAP="mdc_v2.sw_ctrl_map.json"



# ---------- Run the experiments ----------


echo "CTRL FAIL SCEN 1"
OUT="scen1_out.nostats100.txt"
for i in `seq 1 $NUM_TESTS`;
do
    echo "Running test $i of $NUM_TESTS";
    `./EmulateCtrlFail.py --topo $TOPO --scenario $SCEN \
        --sw_ctrl_map $MAP --ctrl_options "$CTRL_OPT" $EXTRA_FLAG >> $OUT`
done

echo "CTRL FAIL SCEN 2"
NUM_TESTS=100
MAP="mdc_v2.sw_ctrl_map.v2.json"
SCEN="Scenario_CtrlFail/scen2.yaml"
OUT="scen2_out.nostats100.txt"
for i in `seq 1 $NUM_TESTS`;
do
    echo "Running test $i of $NUM_TESTS";
    `./EmulateCtrlFail.py --topo $TOPO --scenario $SCEN \
        --sw_ctrl_map $MAP --ctrl_options "$CTRL_OPT" $EXTRA_FLAG >> $OUT`
done
