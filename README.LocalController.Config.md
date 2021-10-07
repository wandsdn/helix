# Local Controller Configuration Documentation #

This readme outlines the supported extra config attributes supported by the
local controller. To specify any of the configuration attributes, the local
controller needs to be started using the `ryu-manager` command with the
`--config-file <file>` attribute. The RUY config module uses the Oslo config
format. The extra configuration attributes may only be provided to the
controller via a configuration file (you can not provide them using an 
argument to the RYU manager command).

The controller supporst several configuration groups which configure different
aspects of the controllers. To specify a group in the config file use the
notation `[<GROUP NAME>]` followed by the configuration attributes in format
`<attribute> = <value>`.



## DEFAULT RYU Attributes ##

** Configuration Group: [DEFAULT] **

ofp_listen_host
: The IP address the controller is listening on for incomming OpenFlow switch
connections.

default_log_level
: The logging level to use for the controller. Requires a python module logging
level code (i.e. 10 DEBUG, 20 INFO, 30 WARN, 40 ERROR, 50 CRITICAL)

_Other attributes are also supported. Please refer to RYU documentation._



## Application ##

Basic controller runtime attributes that configure runtime controller attributes
and behaivour.

** Configuration Group: [application] **

static_port_desc
: Path to CSV file that specifies custom capacity of links (unidirectiona) for
switches connected to the controller. First line of CSV file contains header
that defines what each column (comma value) stores. Format of lines is
`<DPID>,<port>,<speed>` were `<DPID>` is the OF ID of the switch, `<port>` is
the port number of the switch (identifies link) and `<speed>` represents the
capacity of the link/port in bits. If attribute is not set (or custom capacity
of link not defined), controller will use the default OFP attribute of links
to establish capacity of links (used for TE optimisation). _NOTE: first line
of CSV file has to contain the header!_

optimise_protection
: _Defaults to True._ Flag that indicates if protection paths are re-computed
and insatlled by the controller when a topology change is detected. This method
will remove any TE optimisations previously applied to the paths and re-compute
the protection paths based on the current network topology.



## Statistics ##

Attributes that configure controllers stats collection subrutine.

** Configuration Group: [stats] **

collect
: _Defaults to True._ Flag that indicates if the controller should query and
collect regular statistics from the switches it manages. When set, the
controller will collect port send counters from each switch as well as flow
rule byte counters to establish source-destination pair send rates.

collect_port
: _Default to True._ Flag that indicates if the controller should collect port
statistics from the switches it manages. Allows disabling port info collection
and only quering the switches for flow statics (to gather ingress-flow rules).
_Disabling this attribute will implicitly disable TE optimisation as the
controller will no longer detect when a link in the topology is congested._

interval
: _Defaults to 10.0_. Float that defines the number of seconds to wait between
subsequent statistics polling requests to the switches managed by the
controller. Value needs to be a valid float between 0.5 and 600 seconds. _NOTE:
controller-switch latency needs to be considered when setting a poll value to
prevent over burdening the devices and ensure the stats reply arrive and are
processed before the next stats request is generated._

out_port
: _Defaults to False._ Flag that indicates if the controller will output switch
port counter information when it receives a `SIGUSR1` signal. By default, when
the controller receives a `SIGUSR1` signal, the controller will log (using log
level INFO) the active src-dst pair collected statistics. Setting the flag to
true will also display the current switch port send counters.



## Multi-Controller ##

Configure local controller multi-controller communication module attributes and
behaivour.

** Configuration Group: [multi_ctrl] **

start_com
: _Defaults to True._ Flag that indicates if the inter-controller communication
module needs to be started (i.e. if the controller will run in multi-controller
mode and needs to coordinate with other controllers). Setting the flag to true
will spawn extra threads (eventlets) to handle inter-controller communication
and domain leader election. _NOTE: When the flag is set to true, a domain ID
also needs to be provided to the controller._

domain_id
: _Defaults to 0._ Interger that specifies the ID of the domain the local
controller manages/operates in. _When using the controller in multi-controller
mode, ensure that each domain is assigned a unique ID. Only redundant controller
instances that connect to the same set of devices may operate using the same
domain ID._



## TE ##

Configure local controller TE optimisation attributes.

** Configuration Group: [te] **

utilisation_threshold
: _Defaults to 0.90._ Float that specifies the threshold used to detect when a
link is congested. If a links current usage is over the specified threshold,
the link is congested and the TE optimisation module is called. Float needs to
be between 0.0 and 1.0. _NOTE: a very low threshold value will increase the
headroom avaible on the links, i.e. the controller will try to keep the link
usage to the specified percentage of its capacity._

consolidate_time
: _Defaults to 1.0._ Float that specifies the number of seconds to wait before
executed the TE optimisation subrutine (optimise the network). The purpose of
the wait-timer is to consolidate multiple TE optimisation requests into a
single TE optimisation run. _NOTE: The consolidate timer should normally be
smaller than the statistics poll interval value._

opti_method
: _Defaults to "FirstSol"._ String that specifies the name of the TE
optimisation method to use to divert traffic such that usage on a link is
reduced and congestion is addressed. The TE module defines all supported
optimisation methods.

candidate_sort_rev
: _Defaults to True._ Flag that indicates if source-destination pairs
(candidates) should be considered in descending order or ascending when
resolving congestion. True will cause method to consider heavy hitters
(send the most traffic) first.

pot_path_sort_rev
: _Defaults to False._ Flag that indicates if potential path change set
to fix congestion should be sorted in descending order based on the secondary
metric. This flag is only used for certain methods that apply extra metrics
to the set of path changes. "FirstSol" always picks the first valid path
change as the candidate (does not consider multiple modifications) so flag
does not apply. For "BestSolUsage" setting this flag to False will select the
potential path from the set that maximises link usage, while setting to True
will select candidate that minimises path usage (maximise head room).


## Example Configuration File ##


```
[application]
optimise_protection = False
static_port_desc = "port_desc.csv"

[stats]
collect = True
collect_port = True
out_port = False
interval = 5

[te]
utilisation_threshold = 0.90
consolidate_time = 1
opti_method = "BestSolUsage"
path_sort_rev = False
candidate_sort_rev = True

[multi_ctrl]
start_com = True
domain_id = 1234
```


Based on the above configuration file, the controller should not re-compute
protection paths if topology changes are detected, it will load the ports file
`port_desc.csv`. The controller will collect stats and port stats from the
switches and use a poll interval of 5 seconds. Sending SIGUSER to the
controller will not output port counters (only src-dest pair send rates).

The controller will consider a port as congested if its current usage is over
90% of the ports avaible capacity. The controller applies a TE optimisation
delay (consolidation time) of 1 second. The TE optimisation that will be used
is selecting the best solution based on maximum usage. The controller will
consider source-destination pairs in ascending order, i.e. consider the
paths that are generating the least amount of traffic first. The optimisation
method will sort candidates in descending order, selecting the solution that
produced the largest maximum path usage, i.e. maximise link usage while
still avoiding the congested link to resolve congestion (and not causing
congestion elsewhere in the network).

The controller will try to communicate with other controllers via the
multi-controller communication module and the controller is deploayed in a
domain with ID 1234.
