# Experiment - Swap Fixes Multiple Over-Util Ports #

This experiment scenario was created as a early sanity check of Helix's TE
algorithm. The experiment ensures that Helix's TE algorithm correctly detects
when a previous congestion fix resolves congestion for multiple over-utilised
ports. In this experiment, we constrain two ports of a topology and introduce
congestion on both of them. After resolving congestion on the first port, we
expect that Helix's will correctly reduce the usage on the second port, thus
resolving congestion for it and not requiring further path modifications.

This experiment uses the `Networks/TEFixResolvesMultiplPortsTest.py` topology
module:

![TEFixResolvesMultiPortsTest.png Image](/Networks/Diagram/TEFixResolvesMultiPortsTest.png)



## Description ##

The links connecting s1-s2 and s2-s3 are assigned a constrained capacity of
200 Mbps, while the other links in the topology are set to 1 Gbps. The
constrained links are labelled A (s1-s2) and B (s2-s3).

Helix will compute paths for all host pairs in the topology. For this scenario,
traffic will be generated between the left side hosts (h1, h2, h3) to the
right side host (h4). All paths for these hosts use the lower ring of the
topology (s1-s2-s3) as their primary paths and the upper right (s1-s4-s5-s6)
as their secondary paths.

The traffic that we will generated for this scenario is as follows:
    * h1 sends 70Mbps to h4
    * h2 sends 80Mbps to h4
    * h3 sends 90Mpbs to h4

After starting the above traffic streams, links A and B will become congested.
With a default reverse candidate sort order flag (`candidate_sort_rev = True`),
Helix considers the candidates that use the congested ports in descending order
such that the heavy hitters are checked/changed first. Helix will change the
h3-h4 candidate to use its secondary path (upper ring made up of s1-s4-s5-s6),
resolving the congestion on port A.

After applying the modifications, Helix will try to fix the detected congestion
on link B. The previous modification of h3-h4, should also reduce usage on B,
such that B is no longer congested. If Helix's TE algorithm has correctly
modified the usages on the topology and detects that h3-h4 does not use the
congested port, we expect that no further path changes will occur.



## Remarks on Usefulness ##

This scenario was used as an early test to check that the TE algorithm behaves
correctly. Ensuring that the TE algorithm correctly updates link stats after
applying changes and that it detects when a candidate does not use a congested
port is tested using the provided set of code unit tests.
