# SOSR2021 Raw Results & Process Scripts #

This folder contains all raw results and process scripts used to evaluate
Helix. This directory is divided into three sub-directories that evaluate
different aspects.

_Note: The paper only presented part of the control-plane evaluation results
(scenario 1) and part of the TE algorithm evaluation results (AT&T-MPLS
Topology)._



## Data Plane Failure Evaluation #

**Folder:** `SOSR21_ReactVsProact/`

Data plane failure recovery performance evaluation of Helix and comparison
between reactive versus proactive (Helix) recovery collected using two control
channel latencies:
* 4ms
* 20ms - our calculated average WAN latency (see paper for details).


To generate graph using GNU Plot (of processed results data found in
`reactive_vs_proactive.dat` file) use `gnuplot reactive_vs_proactive.p`.
Running this script will generate an SVG image `reactive_vs_proactive.svg`.

Raw results were collected using the collection script
`SOSR2021_collect_react_vs_proact.sh` from the root folder of the repository.


### RAW RESULTS ###

`RAW_RESULTS/` - Contains collected raw and processed
results. Folder also contains process scripts and collection script.

`RAW_RESULTS/ResLinkFail_20ms` - Contains data plane recovery results collected
using a control channel latency of 20ms. Reactive controller results extended
Helix to use a restoration based recovery approach while the proactive and
proactive_alt controllers use Helix's standard protection based recovery method.
The proactive_alt controller slightly modifies how Helix computes path splices.

`RAW_RESULTS/ResLinkFail_4ms` - Contains data plane recovery results collected
using a control channel latency of 4ms.  This folder only contains results for
the reactive controller (proactive controller results were consistent with the
20ms latency results - omitted to save space).

To process the raw results use the `RAW_RESULTS/ResLinkFail_20ms/proc_all.sh`
and `RAW_RESULTS/ResLinkFail_4ms/proc_all.sh` to process the 20ms and 4ms
raw results and output the average recovery time and CI intervals.



## TE Algorithm Evaluation #

**Folder:** `SOSR21_TE/`

Helix TE algorithm evaluation results collected using YATES and presented in
the paper. The paper contained the results for the AT&T MPLS topology (using
the three traffic multipliers). This folder also contains results collected
when evaluating Helix against the other algorithms using the Abilene topology
across three traffic multipliers.

`ConLoss` - Folder that contains congestion loss results. Files used by the
GNU plot scripts which generate graphs for the results (presented in the
paper).

`PathChurn` - Same as `ConLoss` folder but contains path change results.

To generate the graphs presented in the paper for the (AT&T topology) use the
commands:
* `gnuplot attmpls_500.p` - Generate graph for AT\&T MPLS topology (500x
    multiplier)
* `gnuplot attmpls_550.p` - Generate graph for AT\&T MPLS topology (550x
    multiplier)
* `gnuplot attmpls_560.p` - Generate graph for AT\&T MPLS topology (600x
    multiplier)
* `gnuplot abi_2_2.p` - Generate graph for Abilene topology (2.2x multiplier)
* `gnuplot abi_2_8.p` - Generate graph for Abilene topology (2.8x multiplier)
* `gnuplot abi_3_0.p` - Generate graph for Abilene topology (3.0x multiplier)



## Control-Plane Resilience Evaluation ##

**Folder:** `SOSR21_CtrlPlaneFail/`

Helix control plane failure resilience evaluation results collect using the
emulation framework with the first scenario (presented in paper) and second
scenario. The folder contains a script to check if the output data contains
a validation error (`process_find_validation_error.py`) and several scripts
to calculate the metrics based on the emulation framework event output. The
process scripts use the file name format: `process_scen<scen>_<stage>.py` where
`<scen>` represents the scenario number (i.e. 1 and 2) and `<stage>` the
stage number of the experiment we are extracting relevant metrics for.

The `scen1_out.nostat100.txt` and `scen2_out.nostat100.txt` files contain the
raw emulation framework output for our experiments (100 iterations) using the
first and second scenario. `scen1_processed.txt` and `scen2_processed.txt`
files contain the processed metric results from the raw results file (output
of the process scripts collected in a single file).

The raw results were collected using the collection script
`SOSR2021_SOSR2021_collect_ctrlfail.sh` from the root folder of the repository.
The evaluation experiments were collected using two Helix switch-to-controller
mapping files. `mdc_v2.sw_ctrl_map.json` was used to collect results for the
first scenario while `mdc_v2.sw_ctrl_map.v2.json` for the second (contains
extra controller instances).
