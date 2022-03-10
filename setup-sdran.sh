#!/bin/sh

set -x

# Grab our libs
. "`dirname $0`/setup-lib.sh"

if [ -f $OURDIR/setup-sdran-done ]; then
    exit 0
fi

logtstart "sdran"

mkdir -p $OURDIR/sdran
cd $OURDIR/sdran

helm repo add cord https://charts.opencord.org
helm repo add atomix https://charts.atomix.io
helm repo add onos https://charts.onosproject.org
helm repo add sdran https://publicsdrancharts.onosproject.org
helm repo update
if [ ! $? -eq 0 ]; then
    echo "ERROR: failed to update helm with ONF SD-RAN repos; aborting!"
    exit 1
fi

helm install -n kube-system atomix-controller atomix/atomix-controller --version 0.6.7 --wait
helm install -n kube-system raft-storage-controller atomix/atomix-raft-storage --version 0.1.8 --wait
helm install -n kube-system onos-operator onos/onos-operator --version 0.4.9 --wait

kubectl create namespace sd-ran
helm install -n sd-ran sd-ran sdran/sd-ran --set import.onos-kpimon-v2.enabled=true --version 1.1.4

logtend "sdran"
touch $OURDIR/setup-sdran-done
