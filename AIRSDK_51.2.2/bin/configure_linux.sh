#!/bin/bash
# Script to configure a Linux AIR SDK
# to either use x86_64 or arm64 binaries

# Function to change a single link to the provided type
# Parameters:
# 1 = folder to push to
# 2 = name of the link
# 3 = target of the link
create_link() {
  echo Creating link, folder $1, file $2, target $3
  pushd $1 >/dev/null
  rm $2
  ln -s $3 $2
  popd >/dev/null

}

# Function to convert the symbolic links to the $1 input
convert_links() {
  echo Switching to $1
  # find out what our current configuration is...
  current="TBC"
  strCurrent=`file -b adl`
  case $strCurrent in
    *linux64* )
         echo Currently using x86_64
         current="x86_64"
         ;;
    *linux_arm64* )
         echo Currently using arm64
         current="arm64"
         ;;
  esac
  # check we have something to do
  pushd .. >/dev/null
  if [ "$current" == "$1" ]
  then
    echo Nothing to do!
  elif [ "$1" == "x86_64" ]
  then
    create_link bin adl adl_linux64
    create_link lib FlashRuntimeExtensions.so FlashRuntimeExtensions_linux64.so
    create_link lib/nai/bin naip naip_linux64
    create_link runtimes/air linux linux-x64
  elif [ "$1" == "arm64" ]
  then
    create_link bin adl adl_linux_arm64
    create_link lib FlashRuntimeExtensions.so FlashRuntimeExtensions_linux_arm64.so
    create_link lib/nai/bin naip naip_linux_arm64
    create_link runtimes/air linux linux-arm64
  else
    echo Invalid argument - $1
  fi
  popd >/dev/null
}

# First go into the 'bin' folder where this script lies...
dirVal=$(dirname $0)
binFolder=$PWD/$dirVal
pushd $binFolder >/dev/null

target="TBC"

echo
echo Configuring AIR SDK for Linux
if [ "$1" == "" ]
then
  echo
  echo To set up the AIR SDK for running on an x86_64 machine,
  echo or an arm64 machine, use the below command:
  echo
  echo -e '\t./configure_linux [x86_64 | arm64]'
  echo
  # check the current machine for the target
  strMachine=`uname -p`
  case $strMachine in
    *x86_64* )
        echo Machine is x86_64
        target="x86_64"
        ;;
    *aarch64* )
        echo Machine is arm64
        target="arm64"
        ;;
  esac
elif [ "$1" == "x86_64" ]
then
  target="x86_64"
elif [ "$1" == "arm64" ]
then
  target="arm64"
fi

# call the function
if [ "$target" == "TBC" ]
then
  echo Invalid parameter $1
  echo -e 'Please use "x86_64" or "arm64"'
else
  convert_links $target
fi

echo
popd >/dev/null
