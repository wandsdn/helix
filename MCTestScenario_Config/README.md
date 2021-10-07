# Multi-Controller Test Scenario Configuration #

This directory contains controller config files for the Multi-Controller Test
that deploy multiple-controller instances across several areas. For more info
on the test, refer to the `Docs/MCTestScenarios` folder. The folder contains
several diagrams which outline the scenario information as well as the
expected result for each. The topology for the scenarios can be found in the
`Networks` folder.

There are 5 scenario files defined in this directory (V1 - V5). The config
files represent controller configurations for each controller managing the
areas of the topology.


## File Descriptions ##

The files in this directory use the naming convetion `c<ctrl_num>_v<scenario>`
where `<ctrl_num>` is the controller that the file applies to and `<scenario>`
is the scenario number of the file.
