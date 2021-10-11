#/bin/bash

# Script that installs all the required dependencies for using the simulation
# framework and controllers. Please note that this script has to be executed
# as root!


# --- ANSI colour codes ---
INFO="\033[1;34m"
ERROR="\033[0;31m"
OK="\033[1;32m"
CLEAR="\033[0m"


#
# ========== Installing dependencies ==========
#
#echo -e "\n${INFO}[Installing required dependencies]${CLEAR}"
sudo apt install python
sudo apt install mininet
sudo apt install python-pip
sudo pip install --upgrade pip
sudo pip install ryu
sudo pip install pyyaml
sudo pip install numpy


#
# ========== Setup WAND repo for libtrace =========
#
echo -e "\n${INFO}[Installing libtrace]${CLEAR}"
sudo apt-get install curl apt-transport-https gnupg
curl -1sLf 'https://dl.cloudsmith.io/public/wand/libwandio/cfg/setup/bash.deb.sh' | sudo -E bash
curl -1sLf 'https://dl.cloudsmith.io/public/wand/libwandder/cfg/setup/bash.deb.sh' | sudo -E bash
curl -1sLf 'https://dl.cloudsmith.io/public/wand/libtrace/cfg/setup/bash.deb.sh' | sudo -E bash
sudo apt install libtrace4 libtrace4-dev libtrace4-tools libwandio-dev



#
# ========== Make sure the system is up to date ==========
#
echo -e "\n${INFO}[Updating system]${CLEAR}"
sudo apt update
sudo apt upgrade


#
# ========== Check that pktgen is wokring ==========
#
echo -e "\n${INFO}===== MAKE SURE NO ERRORS ARE REPORTED BETWEEN THESE SEPERATORS =====${CLEAR}"
echo -e "${OK}Loading PKTGEN kernel module${CLEAR}"
echo -ne "${ERROR}"
sudo modprobe pktgen
sudo rmmod pktgen
echo -ne "${CLEAR}"
echo -e "${INFO}=====================================================================${CLEAR}"



#
# ========== Compile loggers ===========
#
echo -e "\n${INFO}[Compiling libtrace loggers]${CLEAR}"
cd LibtraceLogger
make
cd ..
