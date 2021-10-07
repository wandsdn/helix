You can configure pktgen using the /proc/ filesystem files. PKTGEN generates packets
on specific seperate threads and CPUs. The default path for pktgens config can be
found in /proc/net/pktgen/

Here you will find several files which have various purposes.

    kpktgend_* - File that outlines the avaiable CPUS for pktgen to use and
                 defines which pktgen interface / thread is bindind to which
                 cpu. When a device needs to be removed we have to write
                 rem_device_all to the CPU file to delete the pktgen interface
                 files.

    pgctrl - File that allows starting of the PKTGEN threads to generate
             packets on the configured interface.

    * - Interface files. Each interface or generation can be configured
        by creating a new interface file, the script will make files in the
        format $ETH@$CPU where $ETH is the interface name and $CPU is the CPU
        we want to use to generate the packets for that specific interface.

Once the PKTGEN generation script has finished, the interface files will contain
stats of the sucesfull execution. These are removed when we rem_device_all or clear
the pktgen device infomration.

NOTE: In order to generate packets on multiple devices using pktgen on mininet, the
hosts have to not be in a seperate namespace. Although we can configure multiple
interfaces which are independent of one another, starting pktgen on multiple
hosts, i.e. writing start to pgctrl, will case the other instances, to lock until
the first pktgen start instance has terminated.

--------------------------------------------------------------------------------------

The process of using pktgen is to add a new device by writting the add_device command
to the specific process file (kpktgend_*) which we want to use for the pktgen generation
thread. Doing this will create the interface file which we write attributes to configure
the pktgen packet generation process.

After we have configured the number of interfaces we want to use, we will then write
start to pgctrl to initiate PKTGEN and start creating packets on the created interfaces.

Once pktgen has finished sending packets (number limit is reached) or script is
terminated, the interface files contain counts relating to the pktgen generation
process.

We will then remove the interfaces (delete them) by writting rem_device_all to the
specific process file (kpktgend_*). We can specific individual CPUs to use for the
generation process.

---------------------------------------------------------------------------------------

Please refer to the document:

    http://www.cs.columbia.edu/~nahum/w6998/papers/ols2005v2-pktgen.pdf

For a outline and explanation of how packet gen works and the attributes that
can be configured
