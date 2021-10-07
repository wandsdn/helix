# TE Code Unit Test: Check Partial Solution #

This testing scenario checks that Helix's TE optimisation works correctly when
accepting partial solutions (partial accept flag is True). A partial solution
is a potential path change for a candidate that causes no congestion loss (can
be over the TE threshold without exceeding capacity of links) and reduces the
overall congestion in the network (the new congestion rate is lower compared to
the old congestion rate). The second criteria for a partial solution prevents
flapping of path changes (moving traffic back and forth between ports in
subsequent optimisation iterations).

The test uses a Helix TE threshold of 50% and the following topology (ports
labeled in square brackets on diagram):

```
SRC--[-1]--[1]--s1--[2]--[1]--s2--[2]--[1]--s5--[4]--[-1]--DST
                ||                          ||
                |+--[3]--[1]--s3--[2]--[2]--+|
                |                            |
                +---[4]--[1]--s4--[2]--[3]---+
```

For this test, Helix will compute a single path between the two host nodes
(SRC to DST). For the scenarios of this test, the link connecting s1-s2 will
become congested.

We assigned the links in the topology the following capacities (in Mbps):

```
SRC---(1000)---s1----(80)----s2---(1000)---s5---(1000)---DST
               ||                          ||
               |+---(1000)---s3----(a)-----+|
               |                            |
               +----(1000)---s4-----(b)-----+
```

The links labelled with `a` and `b` (i.e. s3-s5 an s4-s5) will be assigned
different capacities in the test scenarios to influence the partial accept
selection process and validate its working correctly.

For the following scenarios, we assume that SRC will send 80Mbps to DST.

Regardless of the tested TE optimisation method or assigned Helix flags, the 
TE optimisation algorithm will modify the SRC-DST candidate's path to either:
Pa (SRC-S1-S3-S5-DST), Pb (SRC-S1-S4-S5-DST), nor no change if a valid
solution was not found.



## Scenario 1 ##

_LINK CAPACITY:_ a is set to 160Mbps and b to 80Mbps.

_Expected Results:_
* Partial accept False: all tested TE optimisation methods use Pa
* Partial accept True: FirstSol uses Pa
* BestSolUsage and BestSolPLen use Pa if potential path set sorted in
  ascending order and Pb if descending (flag True)
* CSPFRecomp uses Pa


## Scenario 2 ##

_LINK CAPACITY:_ a is set to 160Mbps and b to 79Mbps.

_Expected Results:_
* All TE optimisation methods use Pa regardless of the partial accept flag
 and potential path candidate reverse sort flag used.


## Scenario 3 ##

_LINK CAPACITY:_ a is set to 100Mbps and b to 140Mbps.

_Expected Results:_
* Partial accept False: all TE optimisation methods fail (no path change)
* Partial accept True: all TE optimisation methods resolve congestion apart
  from FirstSol which does not support partial solutions.
* BestSolUsage and BestSolPLen use Pa if potential path set sorted in ascending
  order and Pb if descending.
* CSPFRecomp uses Pa regardless of the flags.


## Scenario 4 ##

_LINK CAPACITY:_ a is set to 79Mbps and b to 79Mbps.

_Expected Results:_
* All TE methods will fail to resolve congestion regardless of the used flag
values.
* No partial solution exists for this scenario. Ensure that Helix correctly
  detects invalid partials and excludes them from the potential path change
  set.
