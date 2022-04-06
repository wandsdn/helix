# README #

This repo contains the source code for the SDN system and emulation framework
discussed in the SOSR2021 paper
[Helix: Traffic Engineering for Multi-Controller SDN](https://doi.org/10.1145/3482898.3483354).
Helix is a hierarchical multi-controller (MCSDN) system that combines various 
techniques to address performance, robustness and consistency concerns of
deploying TE on WANs. The emulation framework allows evaluating the control
plane failure resilience, data-plane failure resilience and TE optimisation
performance of SDN systems.

The raw results collected to evaluate Helix (presented in the paper) can be
found in the `SOSR2021_RESULTS/` folder of this repo. Please refer to the
folder readme file for info on how results were collected.

To evaluate Helix’s TE optimisation performance, we extended YATES to add
support for evaluating reactive TE algorithms. Our modifications to YATES
and the Helix YATES modules are available [here](https://github.com/wandsdn/helix-te-evaluation).




## Repo Overview ##

This section contains an overview of the items contained in this repo as well
as a description of all the modules used by Helix and the emulation framework.



### Helix Implementation ###

Modules of the Helix MCSDN system. Helix is an OpenFlow controller that uses
the Ryu framework. Helix defines two controller types, local and root
controllers. A local controller connects to and interacts with data plane
devices. The root controller connects to other local controllers and
coordinates inter-domain/inter-area operations.

* `TopoDiscoveryController.py`
    * The base controller module contains code to detect the topology and
      defines shared methods for installing rules and interacting with
      switches. All controller types inherit this module.
* `OFP_Helper.py`
    * Static helper module that contains convenience methods to allow
      building and manipulating OpenFlow rules.
* `ReactiveController.py` (Extends: `TopoDiscoveryController.py`)
    * Alternative SDN controller that implements reactive (restoration) data
      plane recovery. The controller is involved in all failure recovery
      decisions (actively monitors links and recomputes paths when a failure is
      detected).
* `ProactiveController.py` (Extends: `ProactiveController.py`)
    * Helix Local controller that implements proactive (protection) data plane
      recovery. The controller computes multiple rules for each
      source-destination pair and installs using the fast-failover group type.
      Switches will recover from failures without controller intervention.
* `ProactiveControllerAlt.py` (Extends: `ProactiveControllerAlt.py`)
    * Helix local controller that computes loose path splices to improve
      protection coverage. Functionality, both proactive controller modules
      behave the same.
* `TE.py`
    * Helix’s TE optimization module. Defines three TE optimisation methods
      (FirstSol, BestSol, BestSolUsage, CSPFRecompute). Preferred default TE
      method for Helix is CSPFRecompute with a `candidate_sort_rev = True`
      (optimise heavy hitters first).
* `ShortestPath/`
    * Folder that contains modules to store topology information and perform
      path computation (using Dijkstra’s algorithm).
    * `ShortestPath/dijkstra.te` _DEPRECATED_
        * Old simple topology and path computation module which has no support
          for saving port statistics (used for TE).
    * `ShortestPath/code_dijkstra_test.py`
        * Unit tests for `dijkstra.py` module. _See 'Testing' section._
    * `ShortestPath/dijkstra_te.py`
        * Similar to the `dijkstra.py` module, however, it extends topology
          graph to allow storing port/link stats (metrics) for TE.
    * `ShortestPath/code_dijkstra_te_test.py`
        * Unit test for `dijkstra_te.py` module. _See 'Testing' section._
    * `ShortestPath/protection_path_computation.py`
        * Module that contains useful methods to allow computing protection
          paths rebuilding paths from group table entries (used by the
          standard proactive Helix local controller).
* `topo_discovery/`
    * Folder that contains topology discovery code used by the controller.
      Code is an extension of the standard _RYU LLDP_ topology discovery
      code that adds host discovery, inter-domain link discovery, support
      for controller roles, and removes the need for the `--observe-links`
      flag. _Do not use any of the standard RYU topology discovery modules
      as this will auto-start the RYU detection module which can cause
      problems_.
    * `topo_discovery/api.py`
        * Contains convenience methods to send requests to the topology
          discovery instance to retrieve active links and pause/resume
          detection on controller role changes.
    * `topo_discovery/event.py`
        * Events that need to be generated and handlers registered for to
          receive topology discovery information.
    * `topo_discovery/lldp_discovery.py`
        * Actual topology discovery module that runs on a separate
          eventlet instance and performs active detection using LLDP packet
          flooding and retrieval. _NOTE: a special flow rule that matches LLDP
          packets is installed onto the switches to send any packets back to
          the controller_.
* `RootCtrl.py`
    * Helix root controller that performs inter-domain (inter-area)
    operations. _Note: the root controller does not connect to switches so it
    does not implement any Ryu methods._ Root controller relies on local
    controllers (i.e. `ProactiveController.py`) to install forwarding rules
    (interact with the data-plane).



### YATES Wrapper ###

We evaluated Helix’s TE optimisation algorithm using
[YATES](https://cornell-netlab.github.io/yates/) a TE simulation framework.
This section describes the wrappers we call in YATES to simulate Helix's
path computation and TE algorithm. The wrappers import and override the
Helix controller modules to implement shallow controllers that load and
prime data structures with state from files (generated during a YATES
simulation) and execute controller code to perform specific operations (e.g.
compute paths or perform TE),  simulating Helix’s behaviour. _The wrappers
override handler methods and module constructors to disable
connecting/interacting with switches (Ryu specific code and methods), spawning
multiple threads or waiting (e.g. path or TE consolidation timeouts),
and communicating with other switches (e.g. sending or listening for RabbitMQ
messages)_.

The wrappers define several supported actions that require different state
provided as serialized JSON files (generated by YATES) or arguments (run the 
wrappers with the `--help` to see list of supported arguments). When executed,
the wrappers will load the provided state, perform the specified action,
and return the action result by printing a list of path changes (or info) to
standard out. YATES will read and process the output, which is used to modify
the active paths of the current simulation run (apply the specified changes).
All wrappers generate temporary files that contain state that needs to be
saved between calls (e.g. computed path info). All temporary files are saved in
the `/tmp/` folder and use a naming convention of `/tmp/<info>.<CID>.tmp`,
where `<info>` is the info that is stored (e.g. "paths" for paths information)
and `<CID>` the controller identifier (specified as an argument). The temporary
files are generated when calling the compute path ("topo") action and modified
when performing other operations such as TE optimisation. _The compute path
action always needs to be called at the start of every YATES simulation._

* `yates_wrapper.py` _DEPRECATED_
    * Old wrapper that allows testing Helix in single controller mode. This
      wrapper is partially deprecated. To test performance of Helix using a
      single controller, define a map that contains a single device connected
      to all switches in the topology and use `yates_mctrl_wrapper.py`.
* `yates_mctrl_wrapper.py` (Extends: `ProactiveController.py`, `TE.py`)
    * Helix local controller wrapper that allows simulating local controller
      behaivour in YATES. Code defines several actions to simulate Helix's
      behaivour under specific conditions. Network state for each action (e.g.
      topology and link usage information) needs to be provided as a serialized
      JSON file (`yates_mctrl_wrapper.py --help` for list of arguments).
* `yates_root_wrapper.py` (Extends: `RootCtrl.py`)
    * Helix root controller wrapper.



### Emulation Framework ###

The emulation framework allows evaluating the control-plane failure resilience
(discussed in the paper), data-plane failure recovery, and TE optimisation
performance of MCSDN/SDN systems. The emulation framework is built on top of
Mininet, which is used to emulate a virtual topology. Mininet provides support
for emulating network conditions such as link latency, loss or packet
corruption (using `netem`). The emulation framework will consider a SDN
system as a black-box, observing its modifications to the network rather than
interacting with the framework via a specific interface. For more info see
"Emulation Framework" section of this read me.

* `emulator_base.py`
    * Base module of the emulator that contains shared code and useful
      methods to allow easy loading of configuration files and management of
      controllers.
* `EmulateLinkFailure.py`
    * Emulation framework that evaluates data plane failure recovery performance
      of an SDN controller. The emulator generates a constant stream of packets
      using Pktgen, introduces failures in the topology (as defined by a
      scenario file), and computes the time it takes for traffic to be
      redirected to an alternative path (i.e. failure was detected and fixed).
* `EmulateTE.py`
    * Emulation framework that evaluates TE optimisation performance of a SDN
      system. The emulator assesses TE performance by constraining specific
      links in the topology and generating sufficient traffic to introduce
      congestion loss (over-utilise the link). The framework reports the amount
      of time the network experienced packet loss due to congestion. This
      version of the emulator uses Iperf to generate and a stream of packets at
      a constant rate and record packet loss rates.
* `EmulateTEPktgen.py`
    * Similar to `EmulateTE.py`, however, uses Pktgen in combination with packet
      loggers (`TEPerformanceLogger`) written in Libtrace to compute the
      amount of time the network experiences congestion loss. _This version of
      the TE emulation framework is experimental._
* `EmulateCtrlFailure.py`
    * Emulation framework that allows evaluating a SDN system's control plane
      resilience (recovery performance). Framework observes the behaivour of an
      MCSDN (or single controller) system when introducing control plane
      failures (or restarting instances). Framework uses TShark to capture and
      filter OpenFlow packets to detect data plane modifications performed by
      the SDN system (e.g. recompute paths and role changes). The framework
      also has support to capture local controller events (from the controller
      instance log files) to compute components of the primary metrics (e.g.
      failure detection and role change time of the failure recovery metric).
      The framework also acts as a black-box testing tool that ensures that an
      SDN system exhibits correct behaivour under a predefined scenario.
* `LLDP/`
    * Folder that contains scripts to generates packets from host devices to
      allow LLDP host detection (used by Helix).
* `controllers.yaml` _PARTIALLY DEPRECATED_
    * YAML configuration file used by the data plane failure emulator to find
      the controller module that maps to a specified controller name, which
      needs to be started to run the experiment. The framework assumes that
      the module is always the second element in the list of arguments that
      define the controller's start command.
* `controllers_te.yaml` _PARTIALLY DEPRECATED_
    * Encodes similar info as `controllers.yaml`, however, is used by the TE
      performance emulation framework. Similar to the previous config file, 
      only the second argument of the start command is used by the framework
      to retrieve the name of the controller module that needs to be started to
      run the experiment.
* `WaitState/`
    * Contains files used by the data plane and TE emulation frameworks to
      decide when the SDN system has started and entered a stable state before
      running a experiment. The wait state files are JSON files that describe
      data plane rules or characteristics of group/flow table rules installed
      on switches that indicate that the network is stable. The files follow
      the naming convention `<ctrl_name>.<topo_name>.json` and are loaded and
      used automatically by the framework based on the provided arguments.
* `Scenario_LinkFail/`
    * Folder that contains YAML files that describe various link failure
      scenarios which can be used with the data-plane failure framework
      tool to collect recovery time. The scenarios define expected location
      of traffic and links that need to fail to run a failure recovery
      experiment.
* `Scenario_TE/`
    * Folder that contains YAML files that describe TE performance testing
      scenarios which can be used with the TE emulation framework scripts.
      The scenarios define position of traffic capture nodes, volume of
      traffic being generated and controller configuration which is used when
      starting the controller instance (e.g. port speed constraints and TE
      configuration attributes for Helix).
* `Scenario_CtrlFail/`
    * Folder that contains YAML files that describe control plane failure
      scenarios for the control plane failure emulation framework.
* `LibtraceLogger/`
    * Folder that contains the Libtrace packet logger code used by the
      data plane failure emulation framework to compute recovery time. The
      loggers capture Pktgen packets on multiple points in the network and
      compute time-difference between observed packets in the capture files to
      work out the amount of time it took for the SDN system to move traffic
      away from a failed link to a new alternative path.
    * `LibtraceLogger/logger.*`
        * Logger that captures Pktgen packets on a interface and writes the
          captured packet data to a trace file. The logger can either capture a
          certain number of packets and stop (limit mode) or run until a
          SIGINT is received (indefinite capture).
    * `LibtraceLogger/processPKTGE.*`
        * Program that take the captured packet traces of two loggers
          (locations) and calculates the recovery time by computing the time
          difference between the last packet of stream A (node after the failed
          link in the primary path) and the stream B (start of alternative
          path which is used to recover from the failure).
    * `LibtraceLogger/Makefile`
        * Make file that compiles all code in this folder.
* `TEPerformanceLogger/`
    * Folder that contains Pktgen logger and process tools used by the TE
      Pktgen emulation framework.
    * `TEPerformanceLogger/logger.*`
        * Logger that captures Pktgen packets (receivers in experiment). Logger
          behaves similar to `LibtraceLogger/logger.*`.
    * `TEPerformanceLogger/ProcessPKTGEN.*`
        * Program that goes through a trace file and works out the
          aggregated percentage of congestion loss based on the captured
          Pktgen packets. _This program is experimental!_
    * `TEPerformanceLogger/Makefile`
        * Make file that compiles all code in this folder.
* `Networks/`
    * Folder that contains all available topologies for emulation. _See
      "Extra tools and Folders" for more details_.
* `BAD_TRACE/`
    * Folder that contains all traces captured during a data plane
      emulation experiment that reported invalid results (i.e. negative
      recovery time). The bad trace files follow the naming convention
      `<logger location>.<ctrl_name>.<topo name>.pcap`.
* `pktgen.sh`
    * Script used by the data plane failure emulator to configure Pktgen
      to generate a stream of packets to '10.0.0.2'. Pktgen is configured to
      send 512 byte packets with a delay of 0.1ms in between each.
* `pktrem.sh`
    * Script used by the data plane failure emulator to clean up (remove) the
      initiated Pktgen process (initiated by the `pktgen.sh` script).



### Extra Tools and Folders ###

* `Docs/`
    * Folder that contains extra documentation that describes extra testing
      scenarios and other relevant diagrams.
* `Networks/`
    * Folder that contains all available topologies to use for the simulation
    framework.
    * `Networks/Diagram/`
        * Diagrams of topologies
    * `Networks/TopoBase.py`
        * Base topology module that defines shares code. _All topologies
          have to extend the base._
    * `Networks/TestNet.py`
        * Simple topology that is made up of 5 switches and two hosts
    * `Networks/ExtendedTestNet.py`
        * Extended version of test net that has more switches and offers
          more potential alternative paths
    * `Networks/TestPathSpliceFixNet.py`
        * Extended version of `ExtendedTestNet.py` topology.
    * `Networks/LoopTest.py`
        * Script that causes a loop for the proactive controller with a
          specific failure scenario.
    * `Networks/FatTreeNet.py`
        * Generates a k-order fat-tree topology that offers several alternative
          paths (generally found in data centers). To start topology use
          command: `sudo mn --custom FatTreeNet.py --topo topo,k=<K_ORDER>
          --switch ovs --mac --controller remote,ip=127.0.0.1`.
    * `MultiHost.py`
        * Simple topology that defines several switches and multiple hosts.
    * `MultiHostCompPaper.py`
        * Multi host topology presented in 'Fast-Failover and Switchover for
          Link Failures and Congestion in SDN' IEEE ICC 2016 paper.
    * `TETestTopo.py`
        * Topology used for 'TE Swap Over Efficiency Test'.
    * `TEFixResolvesMultiPortsTest.py`
        * Topology used for 'Swap Fixes Multiple Over-Util Ports' scenario.
    * `MPLSCompTopo.py`
        * Topology used to compare TE optimisation performance against a
          standard MPLS-TE deployment emulated in GNS3.
    * `Simple.py`
        * Small topology made up of two hosts and a single switch.
    * `MultiDomainController_v*.py`
        * Topologies used for the multi-domain controller testing scenarios.
          Refer to `Networks/Diagram/MultiDomainController_v*.png` for topology
          diagram and more information on link configuration.
    * `SimpleMultiCtrl.py`
        * Controller role testing topology made up of two hosts and a single
          switch. The switch connects to 3 different controllers on different
          IP addresses.
* `StartTopo.py`
    * Start a Mininet topology and enter the CLI.
* `tools/`
    * Folder that contains useful tools to find ports used by traffic (from
      flow stats), generate wait state files and check state of switches.
      _See 'Helper Scripts' for more information_.
    * `FindPortUsed,py`
        * Query a set of OF switches for OpenFlow port stats and work out what
          fast-failover group port is used when traffic is being forwarded.
    * `GenerateWaitState.py`
        * Helper script that generates a wait state JSON file by querying a
          set of OpenFlow switches for rules and groups currently installed.
    * `StateMatches.py`
        * Helper method that checks and waits for OpenFlow switches to
          transition to a predefined state. This helper module is used by
          the emulator to ensure stable state before starting an experiment.
* `GML_to_MD/`
    * Folder that contains scripts to allow converting a `.gml` topology file
      to a Mininet topology module that can be used with the start topology
      script or emulation framework.
* `MCTestScenario_Config/`
    * Folder that contains Helix controller and port configuration files for
      the Multi-domain controller testing scenarios. For more info on the
      Multi-Domain testing scenarios, refer to `Docs/MCTestScenarios/` for more
      info of each scenario and the expected result.



## Testing ##

This section outlines the different unit-tests and integration tests available
for the controller code and modules. _In addition to the following set of test,
it may be a good idea to go through and collect recovery stats and TE
optimisation stats using the emulation framework, ensuring that the controller
does not crash and produces a result._



### Unit Tests ###

* `ShortestPath/code_dijkstra_test.py` - Unit test that checks the topology
  graph module `ShortestPath/dijkstra.py`.
* `ShortestPath/code_dijkstra_te_test.py` - Similar to previous test however
  checks graph module with TE info support.



### Integration Tests ###

* `code_te_swap_efficiency_test.py` - Prime a dummy controller instance
  with state and perform the "TE Swap Efficiency Tests" outlined in the
  `Docs/TESwapEfficiencyTest.md` read me file. The scenarios in this test
  were initially divides to check that the group port swap based TE methods
  (e.g. FirstSol) behave correctly. After priming the controller with dummy
  state, the test will call the TE optimisation method and check the final
  path and group table information of the controller (i.e. `self.paths`
  dictionary). _This integration test evaluates FirstSol with a ascending
  candidate sort order._
* `code_te_opti_method_test.py` - Similar to the Swap Efficiency Test, but
  checks that the four different TE optimisation methods (FirstSol,
  BestSolUsage, BestSolPLen and CSPFRecompute) behave accordingly. The test
  performs the "TE Opti Method Code Unit Test". For more info refer to the
  `Docs/TEOptiMethodTest` folder.
* `code_te_traffic_change_test.py` - Similar to TE opti method unit test but
  checks that the optimise methods correctly updates link stats if a fix was
  found, and preserves the current metrics if no solution for congestion
  was identified. This test implements all tests defined in the "TE Traffic
  Change Code Unit Test" outlined in `Docs/TETrafficChangeCodeUnitTest.png`.
* `code_te_partial_accept.py` - Similar behaivour to previous unit tests.
  Ensures that the partial accept flag works correctly for the various TE
  optimisation method. The partial accept flag allows the TE method to accept
  solutions which push links over the TE threshold as long as no congestion
  loss occurs. The test implements the "TE Code Unit Test: Check Partial
  Solution" scenarios defined in `Docs/TECodeUnitTest-CheckPartialSol.md`.
* `code_te_partial_accept_ProactiveAltCtrl.py` - Same test as
  `code_te_partial_accept.py` but uses loose path splices which modify the
  groups of the CSPF recomputation method. Initial test uses the standard
  proactive controller (non-loose splices).
* `code_root_ctrl_MCTestScen_v*.py` - Test the Helix root controller by
  priming a dummy instance with state and performing inter-area specific
  operations (requested or sent by the local controller to the root). This test
  performs the MCTestScenarios, described in the
  `Docs/MCTestScenarios/scen-v*.png` diagram. This set of tests assumes
  that the local controllers use the FirstSol (or swap methods) with a reverse
  sort set to False (candidates considered in ascending order). _Note: that
  the candidate TE optimisation method will not affect the root controller,
  however, the info we feed into the root controller differs and is based on
  the local controller configuration.
* `code_root_ctrl_MCTestScen_v*_CSPF.py` - Same as the previous test,
  however, assumes that the local controllers use the CSPFRecomp method with
  a candidate reverse sort flag set to True (candidates considered in
  descending order). For more info refer to the
  `Docs/MCTestScenarios/scen-v2-CSPFRecomp-CandidateRevsort.png` diagrams.



### Black Box Tests ###

* `BlackBoxTests/TETestBase.py` - Base file that contains shared code which
   initiations and executes a black box TE swap test. This module is inherited
   by all black-box tests in this directory. A black box TE swap test is an
   emulation test where a virtual topology and controller instance are
   initiated. Each test scenario uses iperf to introduce congestion into the
   network. The behaivour of the controller is validated by checking the
   resulting path changes in response to the introduced congestion. The test
   uses the ```tools.FindPortsUsed.find_changed_tuple()``` method to detect
   the paths of a source-destination pair.
* `BlackBoxTests/TESwapEfficiencyTest.py` - Runs scenarios defined in the
   "TE Swap Over Efficiency Tests"  (`Docs/TESwapEfficiencyTest.md`) read
   me file. This test uses the FirstSol TE optimisation method with a candidate
   reverse sort flag set to False (algorithm considers candidates in ascending
   order).
* `BlackBoxTests/TESwapEfficiencyTest_CSPF.py`- Runs same scenario as the
   previous TE Swap Efficiency Test, but uses the CSPFRecomp TE
   optimisation method with a candidate reverse flag set to False (sorts
   candidates in ascending order). For more info on expected result refer to
   the "CSPFRecomp TE Optimisation Method Expected Results" section of the
   scenario description file. All results are the same as the previous test
   apart from scenario 3.
* `BlackBoxTests/TESwapEfficiencyTest_CSPF_revsort.py` - Same as the
   above CSPF test but uses a candidate reverse sort flag set to True (sorts
   candidates in descending order).Refer to the "CSPFRecomp TE Optimisation
   Method Expected Results" section of the `Docs/TESwapEfficiencyTest.md`
   read me file.



### Resources and Documents ###

All experiment/unit-test diagrams and documents outlining test results can be
found in the `Docs/` folder of this repository. Diagrams of the topologies
present in `Networks/` can be found in the `Networks/Diagram/` folder.



## Installation and Dependencies ##

_To install all required dependencies and compile everything needed to use the
emulation framework, use the command `sudo bash install.sh`_. Alternatively,
here is a list of all dependencies required by the framework and Helix.

__Requirements for Helix Controllers:__

* _Python_ `sudo apt install python2.7` - Dependency for Ryu/Helix controller
* _Python-PIP_ `sudo apt install python-pip` - Makes installing python modules
  a lot easier.
* _Ryu_ `sudo pip install ryu` - Python OpenFlow framework (used by Helix
  controllers). Further [info on Ryu](https://github.com/faucetsdn/ryu).
  Evaluation results were collected using Ryu version 4.25.
* OpenVSwitch - Evaluation results were collected using OpenVSwitch version
  2.11.1 with DB Schema 7.16.1.

  
__Requirements for Emulation Framework/Tests:__

* _Mininet_ `sudo apt install mininet` - Used by the emulation framework
* _PyYaml_ `sudo pip install pyyaml` - Read YAML text files. The emulation
  framework uses YAML files to describe scenarios and configuration attributes.
* _Libtrace 4_ - Used by the emulation framework to process packet traces and
  calculate the data plane failure recovery metric and TE optimisation time.
  Libtrace 4 can be installed from the 
  [GitHub repository](https://github.com/LibtraceTeam/libtrace).
* _Libtrace 4_ - Refer to the "Libtrace 4" section for instructions. The
  emulation framework uses Libtrace to parse a stream of packets.
* _Pktgen_ - Kernel packet generator module (should already be installed).
    * Kernel module has to be loaded before use (done automatically by the
      emulation framework). Use command `modprobe pktgen` to load module.
    * Module can be unloaded using the command `rmmod pktgen`.
* _Tshark_ `sudo apt install tshark` - Terminal packet capture that utility
  that supports more advanced filtering. Used by the control plane emulation
  framework to capture control plane packets.


  
## Emulation Framework Usage ##

This section describes the arguments and configuration file syntax for the
emulation framework. _Note: the data plane failure resilience and TE
performance evaluation tools of the framework will automatically load and use
a wait state file from `WaitState/<Controller Name>.<Topology Name>.json` 
(based on provided arguments) to check if the network has stabilised. Please
ensure that this file exists in the `WaitState/` folder. Wait stat files can
be generated by running the controller on the network and using the generate
wait state tool (`tools/GenerateWaitState.py`)._



### Controller Definition File - Syntax [Partially Deprecated] ###

The controller definition files used by the controller are `controllers.yaml`
(used by the data plane recovery tool) and `controllers_te.yaml` (used by the
TE performance tool). The files use the following syntax:

```yaml
<name>:
    start_command:
        - ryu-manager
        - <Controller Script>
        - <arg 1>
        - <arg 2>
        - ...
        - <arg n>
```

`name` represents the name of the controller while "start_command" is an array
that defines the actual Ryu (or system) command used to start the controller.
_**NOTE:** The controller definition file is partially deprecated. The emulator
will extract the `<Controller Script>` attribute from the "start_command" list
to initiation the correct controller based on the provided argument. Other
arguments of the command list are ignored. The control plane failure emulator
does not use a controller definition file._



### Emulation Framework Configuration File ###

The emulation framework configuration script allows modifying the local and
root controller start comands as well as define configuration attributes
such as static config blocks.

```yaml
start_cmd:
    local: <start command>
    root <start command>
local_config:
    blocks:
        - [<sort number>, <block name>]
        - ...
    extra:
        <block>:
            <attribute>: <value>
```

The "start_cmd" block allows chaging the local and root controller start
command executed by the framework to start the SDN system. `<start command>`
represents a string to use to start a controller instance. The commands
supports the following placeholder attributes (replaced with actual value
before running the command):

* "{log_level}" - Log level (specified as attribute to emulation framework)
* "{conf_file}" - Path to temporary configuration file generated by the
  framework for the instance.
* "{log_file}" - Path to temporary log file created by the emulation
  framework. Controller instance should use this path as the log location.
  _Note: the control plane failure emulation framework will look at this
  file to extract local events._
* "{cip}" - Controller IP address (control channel address)
* "{dom_id}" - Domain/Aread ID of the controller
* "{inst_id}" - Instance ID of the running instance

_Note: ignore any placeholders from a custom controller start command.
If the start command contains an extra placeholder for which no value
was specified, the placeholder is left unmodified._

The "local_config" block allows specifying the local controller configuration
file syntax and any extra configuration attributes. `<sort number>` represents
a integer used for sorting when generating the instane config file while
`<block name>` the default configuration block instanatiated. The list
of arrays is converted to a tuple when processing.

Finally, "extra" of the "local_config" blocks allows specifying extra
configuration attributes added to the config file of every start local
controller instnace. `<block>` is the name of the block the config
attribute applies to while `<attribute>` is the name of the attribute
and `<value>` the value to assign. For example, to stop Helix from
collecting stats for TE, use the following:

```yaml
local_config:
    extra:
        stats:
            collect: False
```

_Note: if the emulation framework is started without a switch-to-controller
map, the framework will implicitly add "start_com: False" to the "multi_ctrl"
configuration block. This tells Helix to not intiate any inter-controller
communication modules or threads (eventlets)._



### Link Failure / Data Plane Failure Tool ###

The data plane failure tool allows evaluating the data plane recovery
performance of a SDN system. The tool/script uses Mininet to emulate a network.
The tool will introduce failures to the data plane based on a scenario file and
calculate the time it takes the SDN system to recover from the failure (divert
traffic away from the failed links. The tool uses Pktgen to generate a stream
of packets during an experiment. Two Pktgen packet loggers are deployed on
different locations in the topology. The first logger captures packets on the
primary path while the second on the expected alternative path (path used after
the SDN controller recovers from the failure). Recovery time is computed as
the Pktgen timestamp difference between the first packet observed by the
second (backup path) logger trace and the last packet observed by the first
(primary path) logger.


** Usage:**
```
./EmulateLinkFailure.py --topo <topo> --controller <ctrl> \
    --failure <fail> --sw_ctrl_map [map] --ctrl_options [CTRL OPTIONS] \
    --log_level [log_level] --ctrl_log_level [ctrl_log_level] \
    --config_file [config_file]

    <topo> - Topology module to use for experiment specified as either a
        file path or import dot notation.
    <ctrl> - Name of controller to use for the experiment (defined in the
        controllers.yaml file).
    <fail> - Path to failure scenario to use for the experiment.
    [map] - Optional switch-to-controller map file. Specifying a map file will
        run an emulation experiment using multiple controllers and instances.
    [CTRL OPTIONS] - Optional Netem attributes to apply to the control channel
        (e.g. 'delay 20ms' adds 20ms one-way latency to the links).
    [log_level] - Custom logger level to use for experiment output (defaults
        to "critical").
    [ctrl_log_level] - Custom logger level to use for the Helix controllers
        (defaults to "critical). Similar to framework output but applies to
        the controller temp files (generated during the experiment).
    [config_file] - Optional path to emulation framework configuration file
        that specifies controller start command and other config attributes.
        Defaults to "EmulatorConfigs/config.LinkFail.yaml".
```

_Example: to run an experiment using "scenario 1" with the "proactive"
controller on the "Test Net topology" we would use the command:

```
./EmulateLinkFailure.py --topo Network.TestNet --controller proactive \
    --failure Scenario_LinkFail/fail_1.yaml
```

The syntax for the data plane link failure scenario file is:

```yaml
failure_name: "<name_of_scenario>"
failed_links:
    - <failed_link>
    - ...
logger_location:
    <controller_name>:
        primary:
            switch:
                - <primary_sw_logger>
                - ...
            interface:
                - <primary_sw_intf_logger>
                - ...
            port:
                - <primary_sw_port_logger>
                - ...
        secondary:
            switch:  
                - <secondary_sw_logger>
                - ...
            interface:
                - <secondary_sw_intf_logger>
            port:
                - <secondary_sw_port_logger>
    ...
usable_on_topo:
    - <topo_name>
    - ...
```

`<name_of_scenario>` is the name of the failure scenario. The field
"failed_links" contains a list of `<failed_link>` (syntax `<sw>-<sw>`). During
the experiment, the framework will fail the links one at a time (recovery time
calculated and reported for each).

The section "logger_location" defines the position of the loggers used for all
links that will fail in the scenario. `<controller_name>` represents the name
of the controller the logger locations apply to. `<primary_sw_logger>`,
`<primary_sw_intf_logger>`, and `<primary_sw_port_logger>` specify the location
of the Pktgen packet logger on the primary path (hop after the failed link).
`<scondary_sw_logger>`, `<scondary_sw_intf_logger>`, and
`<secondary_sw_port_logger>` specifies the location of the logger on the
secondary path (recovery path). The framework calculates the failure recovery
metric by calculating the difference between the first packet observed on the
secondary logger and the last packet on the first logger.

_NOTE: the list of loggers coincides with each failed link where the first
logger location applies to the first failed link._

If a scenario does not apply to a specific topology (name of topology to use
for the experiment is not defined in "usable_on_topo"), the framework will exit
without running the experiment.



### TE Optimisation ###

The TE optimisation emulator tool/script allows evaluating a SDN system's TE
optimisation performance. The tool is similar to the other emulation framework
tools. The tool generates traffic using either Iperf or Pktgen (depending on
the version). During an experiment, the tool will generate traffic on the
topology based on a scenario file. To evaluate TE optimisation performance,
the tool will introduce sufficient traffic in the network to cause packet
loss to occur (over-utilise links). TE optimisation performance is evaluated
by calculating the amount of time it takes an SDN system to modify its current
paths to resolve the introduced congestion. The tool uses Gnuplot to generate
a graph of the recorded congestion loss rate for an experiment. Output files
uses the naming convention `<name>_<stream number>.<ext>` where `<name>`
represents the info (e.g. "graph" for graph image file), `<stream number>` the
traffic stream number (as defined in the  "send" section of the scenario file),
and `<ext>` the file extension (e.g. "png" for the graph image). Results are
generated for every stream of traffic used in a experiment (defined in the
scenario file; list of "send" info).

** Usage:**
```
./EmulateTE.py --topo <topo> --controller <ctrl> --scenario <scen> \
    --sw_ctrl_map [map] --ctrl_options [CTRL OPTIONS] \
    --log_level [log_level] --ctrl_log_level [ctrl_log_level] \
    --config_file [config_file]

    <topo> - Topology module to use for experiment.
    <ctrl> - Name of controller to use for the experiment.
    <scen> - Path to scenario file to use for the experiment.
    [map] - Optional switch-to-controller map file. Specifying a map file will
        run an emulation experiment using multiple controllers and instances.
    [CTRL OPTIONS] - Optional Netem attributes to apply to the control channel
        (e.g. 'delay 20ms' adds 20ms one-way latency to the links).
    [log_level] - Custom logger level to use for experiment output (defaults
        to "critical").
    [ctrl_log_level] - Custom logger level to use for the Helix controllers
        (defaults to "critical). Similar to framework output but applies to
        the controller temp files (generated during the experiment).
    [config_file] - Optional path to emulation framework configuration file
        that specifies controller start command and other config attributes.
        Defaults to "EmulatorConfigs/config.TE.yaml".
```

`EmulateTE.py` uses Iperf to generate a stream of packets and collect metrics
(i.e. packet loss rate), while the second version `EmulateTEPktgen.py` uses
Pktgen and Libtrace loggers to calculate the loss rate. Both versions of the
TE optimisation tool (scripts) use the same arguments and produce the same
metrics (using different methods). _Note: `EmulateTEPktgen.py` is considered
experimental (use `EmulateTE.py` instead)._

The syntax for the TE optimisation scenario file is:

```yaml
scenario_name: "<name_of_scenario>"
scenario:
    <controller_name>:
        send:
            - src_host: <src_host>
              dest_addr: <dst_addr>
              rate: <send_rate>
              delay: <delay>
            - ...
        receive:
            - host: <host>
        stream_time: <packet_send_time>
    ...
usable_on_topo:
    - <topo_name>
port_desc: |
    <port_desc>
te_conf:
    <te_conf>
```

`<name_of_scenario>` is the name of the TE scenario and `<controller_name>`
represents the name of the controller the scenario applies to (e.g.
"proactive"). The "send" section defines the Pktgen or Iperf sender attributes,
while the "receive" section the receiving server details. `<src_host>` is the
name of the host that is generating the traffic, `<dst_addr>` the IP of the
receiver (where to send the traffic to), `<send_rate>` the transmission
rate (e.g. 50M for 50 Mbits/s), and `<delay>` is the number of seconds to
wait before starting to send packets. `<packet_send_time>` represents the
number of seconds the scenario runs for (i.e. experiment ends after n seconds).

`<topo_name>` is the name of the topology that this scenario is usable on,
while `<port_desc>` the Helix port description file to use for the experiment,
and `<te_conf>` a list of Helix TE attributes. The port description file tells
Helix the capacity of links in the network (tells the controller to limit
traffic on a link to n bytes). The syntax for `<port_desc>` is (header always
needs to be present):

```csv
dpid,port,speed
<dpid>,<port><speed bytes>
```



### Control Plane Failure ###

The control plane resilience emulation tool/script allows evaluating a SDN
systems control plane resilience. The tool will treat a SDN system as a
black-box, observing its behaviour under a predefined failure scenario by
collecting control plane events on control-channel (e.g. OpenFlow role change
and path re-computation messages)  The will use the collected events to allow
calculating metrics such as recovery time and controller/area join time. The
framework also has support to compute components of metrics. For example,
failure detection time and role change time of the instance failure recovery
metric. _Componenent value calculation requires support from the SDN system
as components are calculated through local events (localised controller
state changes) that are pushed by the SDN system to their logs._

The tool allows emulating both simultaneous or cascading failures and supports
three action tyoes:

* Stop a controller instance
* Start a controller instance
* Introduce a delay

To execute an experiment, a failure scenario needs to be provided as arguments
to the framework. A failure scenario is divided into multiple stages which
contain a set of actions to execute. The framework will end a stage after 360
seconds of event inactivity (no events occur). After the stage ends, the
framework processes the collected timeline of events and outputs the relevant
information. The framework will then move to the next stage of the file or end
the current experiment. _Note: controllers are not restarted after every stage
so state is carried throughout the entire experiment, across all stages._

Dividing the failure scenario into stages allows the framework to attribute
specific events to a particular set of actions.

The framework collects two event types, control plane and local events.
Control plane events are collected by monitoring the control-channel. In our
case, the framework uses Tshark to capture relevant OpenFlow packets of type:

* Role change request
* Group modification request (modify/install paths)
* Flow modification request (modify/install paths)

Local events are captured by monitoring the SDN system logs. The SDN system
should output a line to their log files that follow the syntax
`XXXEMUL,<timestamp>,<extra info>,...`.  Local events allow us to calculate
component values of metrics such as working out the amount of time it took the
SDN system to detect the failure and respond to the failure by modifying its
role.

** Usage:**
```
./EmulateCtrlFail.py --topo <topo> --sw_ctrl_map <map> --scenario <scen> \
    --ctrl_options [CTRL OPTIONS] --log_level [log_level] \
    --ctrl_log_level [ctrl_log_level] --config_file [config-file]

    <topo> - Topology module to use for experiment.
    <scen> - Path to scenario file to use for the experiment.
    <map> - Switch-to-controller map file which defines controllers,
        areas/switches they manage, and instances to deploy in each cluster.
    [CTRL OPTIONS] - Optional Netem attributes to apply to the control channel
        (e.g. 'delay 20ms' adds 20ms one-way latency to the links).
    [log_level] - Custom logger level to use for experiment output (defaults
        to "critical").
    [ctrl_log_level] - Custom logger level to use for the Helix controllers
        (defaults to "critical). Similar to framework output but applies to
        the controller temp files (generated during the experiment).
    [config_file] - Optional path to emulation framework configuration file
        that specifies controller start command and other config attributes.
        Defaults to "EmulatorConfigs/config.CtrlFail.yaml".
```



#### Switch-to-Controller Mapping File Syntax ####

```json
{
    "root": {"<rid>": <info>},
    "ctrl": {
        "<cid>": {
            "sw": ["<sw_name>", ...],
            "host": ["<host_name>", ...],
            "extra_instances": ["<inst_id>", ...],
            "dom": {
                "<n_cid>": [
                    {"sw": "<sw_from>", "port": "<pn_from>", "sw_to": "<sw_to>", "port_to": "<port_to>"},
                    ...
                ],
            },
        ...
        },
    },
}
```

The map is separated into two parts, the "root" block that contains info
relating to the root controllers and the "ctrl" block that describes the
areas of the topology and local controller clusters. Value of both blocks
should be a dictionary where the key defines the ID of the controller being
defined. `<rid>` defines the ID of the root controller while `<info>` is
a dictionary object that contains the information related to the root
controller.

`<cid>` is the ID of the local controller the information applies to. Every
local controller (cluster) definition contains three attributes that outline
the controller information and area definition for the controllers. The "sw"
attribute defines a list of `<sw_name>` or switch names the controller cluster
manages while the "host" attribute a list of `<host_name>` or host names in
the area. The "extra_instances" attribute contains a list of instance IDs
(`<inst_id>`) deployed in the area local controller cluster. Finally the "dom"
attribute contains a dictionary which defines the inter-area links for the
current local controller cluster (area). `<n_cid>` of the neighbouring area
dictionary represents the ID of the neighbouring area while the value of
the attribute is a list of inter-area links (identified as a from and to switch
and port quad).

**Example switch-to-controller map extract and its interpretation by the
emulation framework:**

```json
{
    "root": {"r1": {}},
    "ctrl": {
        "c1": {
            "sw": ["s1", "s2", "s3"],
            "host": ["h1"],
            "extra_instances": [],
            "dom": {
                "c2": [
                    {"sw": "s2", "port": "1", "sw_to": "s4", "port_to": "5"},
                    {"sw": "s2", "port": "2", "sw_to": "s5", "port_to": "1"}
                ]
            }
        },
        "c2": {
            "sw": ["s4", "s5", "s6", "s7"],
            "host": ["h2", "h3"],
            "extra_instances": [1, 2, 3, 4],
            "dom": {
                "c1": [
                    {"sw": "s4", "port": "4", "sw_to": "s2", "port_to": "1"},
                    {"sw": "s5", "port": "1", "sw_to": "s2", "port_to": "2"}
                ]
            }
        }
    }
}
```

The above map file defines two controller cluster/areas. Cluster "c1" or area
"c1" contains nodes "s1", "s2", "s3", and "h1". The "c1" cluster contains a
single controller instance (defacto instance ID is 0). Cluster "c2" or area
"c2" contains nodes "s4", "s5", "s6", "s7", "h2" and "h3". The "c2" cluster
contains five instances numbered with ID 0 (defacto/default implicity), 1, 2, 3
, and 4. Area 1 ("c1" cluster) is interconnected to area 2 ("c2" cluster) by
two inter-area links. The first inter-area link joins area 1 to 2 from switch
"s2" port 1 to switch "s4" port 5 and the second link from switch "s2" port 2
to switch "s5" port 1.

_NOTE: a local controller/area definition always has an implicit instance
(labelled with ID 0). As a result, the "extra_instances" should be labelled
starting from 1 (do not use label 0)._



#### Control Plane Failure Scenario File Syntax ####

```yaml
scenario_name: "<name_of_scenario>"
scenario:
    - delay: <stage_delay>
      actions:
          - ctrl: <cid>
            inst_id: <inst_id>
            op: <op>
            [wait: <wait>]
            ...
      expected:
        local_leader_elect: <lc_elect>
        local_path_recomp: <lc_path>
        root_path_recomp: <rc_path>
    - ...
```

`<name_of_scenario>` is the name of the control plane failure emulation
scenario. The stages of the scenario are written as elements of the "scenario"
block. Each stage contains three attribute blocks. First, `<stage_delay>`
represents the number of seconds the emulation framework should wait before
starting to execute the actions. Second, the "actions" block contains the set
of actions to execute, in order. All action objects (blocks) contain a `<cid>`
that identifies the controller cluster the action applies to and a `<inst_id>`
which identifies the instance. The framework will label instances sequentially
starting from instance number 0 which, at the start of the experiment, is the
primary instance. Action blocks also need to specify an `<op>` that contains
the operation to apply to the identified controller. `<op>` can either be
"start" to start the instance or "fail" to fail the controller instance. To
introduce a delay/timeout between executing actions, every action block can
also contain a "wait" attribute (optional). The wait attribute of the action
is interpreted by the framework as the timeout action (specified above).
`<wait>` will tell the tool to wait n seconds before executing the next action
in the set. Finally, a stage will contain a "expected" block of flags that
tell the framework which operations we expect the SDN system to perform in
response to the set of actions that are executed. All flags should be encoded
as Boolean strings ("True"/"False"). If `<lc_elect>` is set to true, the
framework checks if the collected event timeline contains local leader election
events. If `<lc_path>` is true, the framework checks that the timeline contains
local path computation events. If `<rc_path>` is set to true, the framework
checks that root controller paths installations/modifications were detected.

_Note: while a finer granularity of expected events is easy to add to the
framework, we deemed this functionality to not be very useful. Theoretically we
can tell the framework that we expect controller X to do this but we also
wanted to allow the SDN system flexibility to decide which controller responds.
For examole, while Helix's election process is based on IDs and is thus
deterministic, other systems may use other forms of deciding the controller
that takes over a cluster. To account for this situation, our validation
process is simply based on the overall action type, i.e. for this set of
scenarios, if our implementation of the SDN system works, we expect the
system to localise reaction to the set of actions and not perform other
operations such as modifying paths. Furthermore, a courser granularity of the
expected event field greatly reduces the difficulty to define new scenarios!_


** Example Scenario and Interpretation by Framework **

```yaml
scenario_name: "Test scenario"
scenario:
    - delay: 0
      actions:
          - ctrl: 1
            inst_id: 0
            op: fail
          - ctrl: 2
            inst_id: 0
      expected:
        local_leader_elect: True
        local_path_recomp: False
        root_path_recomp: False
    - delay: 5
      actions:
          - ctrl: 1
            inst_id: 1
            op: fail
            wait: 5
          - ctrl: 1
            inst_id: 1
            op: start
      expected:
        local_leader_elect: False
        local_path_recomp: True
        root_path_recomp: False
```

The above scenario contains two stages. The effective timeline of the
experiment is as follows:

```text
START OF EXPERIMENT

* STAGE 1
    Fail instance 0 from controller cluster (area) 1
    At the same time fail instance 0 from controller cluster (area) 2

    = Stage Ends (after 360 seconds of inactivity) =

    Output results and ensure:
        * Local controller role changes detected in timeline
        * No path modifications detected in timeline

* STAGE 2
    Wait 5 seconds (a timeout event of 5 seconds)
    Fail instance 1 of controller cluster 1
    Wait 5 seconds (a timeout event of 5 seconds)
    Start instance 1 of controller cluster 1

    = Stage Ends (after 360 seconds of inactivity) =

    Output results and ensure:
        * No role changes detected in timeline
        * Local controllers modified paths
        * No inter-area path modifications detected

END OF EXPERIMENT
```



#### How Observed Events are Associated with Instances ###

The emulation framework multi controller manager defined in
`emulator_base.ControllerManager` will process the switch to controller mapping
file and automatically start the define instances. Each controller instances
is assigned a unique localhost IP address that it uses on the control channel.

The IP addresses assigned to the controller instances follow the syntax
`127.0.0.<n>` where `<n>` represents a sequential integer (incremented for
each instance) starting from 11. For example, the first controller instance
defined in the switch controller file (C1 instance 1) will be assigned the IP
address "127.0.0.11", while the second instance "127.0.0.12".

When a control channel event is captured, the emulation framework will
associate the event to a controller instance by resolving the source IP address
of the packet to a controller identifier (find the ID of the controller
instance that was assigned this IP address).

When capturing local events, the framework associated a local event to a
controller instance based on which log file the event was observed. The
framework assumes that each started instance will write to a unique log file,
automatically crated and assigned to the instances.




#### Resolving Path Modification Rules to Source-Destination Paris ####

The tool decides if a particular flow modification packet (request) is for an
inter-area link by extracting the GID or rule identifier and re-mapping it to
the relevant source-destination pair.

_How we integrated with Helix:_

Helix uses a protection based recovery mechanism where each source-destination
pair is assigned a unique ID (calculation of ID is based on the host/node IDs).
The emulation framework uses the provided function to map a group ID to a
path pair. After resolving the source-destination pair key, the tool is able to
go through the area information to figure out if a path modification control
channel event is related to an inter-area path modification or a local change.

_Note: if no map or function is provided, the framework will not resolve the
events and treat all events as local path modifications (cannot check for
inter-area path changes when validating behaviour!)_

The static function to resolve a Helix GID to a source-destinatipn pair key is
defined in `TopoDiscoveryController.get_reserve_gid()`.



#### Output Example and Metric Calculation ####

After every stage of the experiment, the tool outputs the set of actions
executed for the stage and its internal timeline as two CSV formated sections
to standard output. The two sections are seperated using a "----" delimitator.
The syntax of the output generated by the tool is:

```csv
<stage_num>,<cid>,<inst_id>,<op>,<ts>
...
<stage_num>,<cid>,<inst_id>,<op>,<ts>
----
<stage_num>,<id>,<ts>,<rts>,<type>,<info>
...
<stage_num>,<id>,<ts>,<rts>,<type>,<info>

----

... NEXT STAGE, SYNTAX REPEATED ...

````

The first block of output contains the set of actions executed during the stage
while the second block the framework timeline which describes an ordered list
of both executed actions and events.

`<stage_num>` represents the stage number the output relates to. The first
stage is labelled 0, the next 1 and so on.

For the action output, `<cid>` represents the ID of the cluster the action
applies to while `<inst_id>` the intance. If the action applies to the
implicit (instance 0), `<inst_id>` will be set to "None" (empty string).

For the action output `<op>` shows the operation (i.e. "fail" or "start").

Both blocks contain a `<ts>` attribute (at different position) which defines
the time the action occured or event was observed represented by a float.
In the timestamp, whole numbers encode the number of seconds from epoch and
decimals the milliseconds.

_NOTE: in the timeline section, actions are encoded using a different syntax
compared to the first block. The action encoding syntax matches the events._

For the timeline output, `<id>` represents the identifier of the instance
an event is associated with or an action applies to. `<id>` is a combination
of `<cid>` and `<inst_id>` that uses syntax `<cid>.<inst_id>`. When refering
to instance 0 of a cluster, `<id>` will simply be set to `<cid>` (e.g.
instance 0 of the "c1" cluster, `<id>` is set to "c1").

For the timeline output, `<rts>` represents the timestamp difference between
the current event/action and the previous even/action for the current device.
If a particular event/action is the first element of the timeline that applies
to a specific instance (`<id>`), `<rts>` will be 0.0000.

`<type>` represents the type of item in the timeline. "action" indicates that
the timeline entry is a performed action, "event_ofp" that the item is a
captured control channel event and "ofp_local" the item is a captured local
event.

`<info>` field contains the attributes of the timeline item and varies
depending on the type of event being encoded. Normally, the first CSV
attribute of the `<info>` element contains the sub-event type for events
(e.g. "role" for control channel role change) or `<op>` field for an
action.

Example output (left hand side column represents output numbers):

```text
 1   0,c1,None,fail,1614050837.842162
 2   0,c2,None,fail,1614050837.852842
     -----
 3   0,c1,1614050837.842162,0.000000,action,fail,c1
 4   0,c2,1614050837.852842,0.000000,action,fail,c2
 5   0,c2.1,1614050838.753311,0.000000,event_local,inst_fail,0
 6   0,c2.1,1614050838.753811,0.000500,event_local,role,master
 7   0,c2.1,1614050838.791385,0.037575,event_ofp,role_change,master
 8   0,c2.1,1614050838.791505,0.000120,event_ofp,role_change,master
 9   0,c1.1,1614050839.131422,0.000000,event_local,inst_fail,0
10   0,c1.1,1614050839.131598,0.000176,event_local,role,master
11   0,c1.1,1614050839.163881,0.032283,event_ofp,role_change,master
12   0,c1.1,1614050839.163898,0.000018,event_ofp,role_change,master
     -----
13   1,c2,None,start,1614050854.413224
     ----
```

Above output contains two stages labelled 0 and 1 (i.e. "s0", "s1"). The first
stage performed two simultaneous actions, fail instance "c1.0" (implicit
instance) of area 1 and instance "c2.0" (implicit instance) of area 2.

The framework executed action #1 on Tuesday, 23 of February 2021 at 03:27:17
842162 ms. Both action #1 and #2 are also present in the timeline output
(element #3 and #4). The timeline output includes shows two discreet changes
occuring, one affecting the c1 cluster and one affecting the c2 clsuter. We
will describe the behaivour of the "c1" cluster ("c2" behaves the same).

After the failure of "c1.0", the remaining active backup instance ("c1.1"),
detects the failure of the primary instance (#9). "c1.1" responded to the
failure by changing its role to master (#10). It took "c1.1" 0.5ms (difference
between #9 and #10) to begin changing its role. On the timeline we can
see that "c1.1" requests a role change for two switches (in its area).

The recovery metric (Trc) is calculated for each individual affected cluster.
For "c1", the recovery metric is calculated by finding difference between
the last relevant action applied to the cluster (i.e. #3 failure of "c1.0")
and the last role change request message (response to the failure) or
event #12. The recovery metric for the "c1" cluster was 1.321736 seconds.

Based on the timeline output, we can compute two componenent values of the
recovery metric, failure detection (t_fd) and role change time (t_rc).
Failure detection represents the time it took the backup instance to detect
the failure of the primary instance in the cluster which can be calculated by
finding the difference between the last relevant action and the last failure
detection event (i.e. #3 and #9). The failure detection componenent for the
"c1" cluster was 1.28926 seconds. Role change time can be calculated as the
difference between the last failure detection event and the last role change
event (i.e. #9 and #12). It took "c1.1" 0.032476 seconds (32.476 ms) to
respond to the failure by changing its role.

Recovery time is equal to detection time plus the role change time
`Trc = t_fd + t_rc`.

_Note: the SOSR2021 result folder contains scripts which process the output
generated by the control plane failure emulation tool and compute metrics
and componenent values._



## Helper Scripts ##

This repo provides several helper scripts that aim to aid certain tasks. These
scripts are avaible in the `tools/` folder of the repo.



### Find Ports Used Script ###

The `tools/FindPortsUsed.py` script outputs the Helix fast-failover ports used
to forward traffic on a switch based on group buckets and packet counters.
The script will retrieve the current group port stats by using the
`dpctl dump-group-stats -O OpenFlow13` command, wait several seconds (or wait
for user input) and retrieve the new counter values. The script compares the
new with the old group port values to indicate which ports were used to
forward traffic on each switch (specified as an argument).

** Usage:**
```
./FindPortsUsed.py [--switches sw] [--wait_enter] [--wait_time time]

    [sw] - List of switches to check used ports of. Format: "s1,s2,..."
        If not specified, defaults to s1,s2,s3,s4,s5.
    --wait_enter - Flag that tells the script to wait for user to press
        the enter key before finding the modified (incremented) switch
        group stats.
    [time] - Wait for n seconds before outputing the used ports. Note:
        the wait enter flag takes precedence (if specified wait for user
        to press the enter key).
```


### Generate Framework Wait State File ###

The `tools/GenerateWaitState.py` script queries a set of switches for their
OpenFlow group and flow rules, generating a wait state file. The wait state
file is used by the data-plane and TE emulation framework scripts to check
if a controller has stabilised before starting an experiment. Wait state
files need to be generated for each unique topology. Internally the script
will use the `ovs-ofctl dump-flows -O OpenmFlow13 <sw>` and
`ovs-ofctl dump-groups -O OpenFlow13 <sw>` commands to query a switch for its
flow and group rules. The retrieved inforamtion is processed into a wait
state dictionary. _NOTE: the wait state file describes a set of features
(rather than the actuall rules) so some of the info retrieved from the
switches is santized before generating the wait state output dictionary,
making the wait state more generic. The wait state files has full regex
support for matching so patterns may be used instead of values to further
characterize the stable state of the SDN system._

**Usage:**
```
./GenerateWaitState.py [--switches sw] --file <file>

    [sw] - List of switches to check used ports of. Format: "s1,s2,..."
        If not specified, defaults to s1,s2,s3,s4,s5.
    <file> - Output file that contains the extracted wait state dictionary.
```
