#!/usr/bin/env python

import geni.portal as portal
import geni.rspec.pg as RSpec
import geni.rspec.igext as IG
# Emulab specific extensions.
import geni.rspec.emulab as emulab
from lxml import etree as ET
import crypt
import random
import os.path
import sys

TBCMD = "sudo mkdir -p /local/setup && sudo chown `geni-get user_urn | cut -f4 -d+` /local/setup && sudo -u `geni-get user_urn | cut -f4 -d+` -Hi /bin/sh -c '/local/repository/setup-driver.sh >/local/setup/setup-driver.log 2>&1'"

#
# For now, disable the testbed's root ssh key service until we can remove ours.
# It seems to race (rarely) with our startup scripts.
#
disableTestbedRootKeys = True

#
# Create our in-memory model of the RSpec -- the resources we're going
# to request in our experiment, and their configuration.
#
rspec = RSpec.Request()

#
# This geni-lib script is designed to run in the CloudLab Portal.
#
pc = portal.Context()

#
# Define some parameters.
#
pc.defineParameter(
    "nodeCount","Number of Nodes",
    portal.ParameterType.INTEGER,1,
    longDescription="Number of nodes in your kubernetes cluster.  Should be either 1, or >= 3.")
pc.defineParameter(
    "nodeType","Hardware Type",
    portal.ParameterType.NODETYPE,"d430",
    longDescription="A specific hardware type to use for each node.  Cloudlab clusters all have machines of specific types.  When you set this field to a value that is a specific hardware type, you will only be able to instantiate this profile on clusters with machines of that type.  If unset, when you instantiate the profile, the resulting experiment may have machines of any available type allocated.")
pc.defineParameter(
    "linkSpeed","Experiment Link Speed",
    portal.ParameterType.INTEGER,0,
    [(0,"Any"),(1000000,"1Gb/s"),(10000000,"10Gb/s"),(25000000,"25Gb/s"),(40000000,"40Gb/s"),(100000000,"100Gb/s")],
    longDescription="A specific link speed to use for each link/LAN.  All experiment network interfaces will request this speed.")
pc.defineParameter(
    "ricRelease","O-RAN SC RIC Release",
    portal.ParameterType.STRING,"dawn",
    [("cherry","cherry"),("dawn","dawn")],
    longDescription="O-RAN SC RIC component version.  Even when you select a version, some components may be built from our own bugfix branches, and not specifically on the exact release branch.  This parameter specifies the default branch for components that we can use unmodified.")
pc.defineParameter(
    "installORANSC","Install O-RAN SC RIC",
    portal.ParameterType.BOOLEAN,True,
    longDescription="Install the O-RAN SC RIC (https://wiki.o-ran-sc.org/pages/viewpage.action?pageId=1179659).  NB: the NexRAN xApp only works with the OSC RIC at present, so you should leave this enabled.",
    advanced=True)
pc.defineParameter(
    "buildORANSC","Build O-RAN SC RIC customizations from source",
    portal.ParameterType.BOOLEAN,False,
    longDescription="We maintain local patches for some O-RAN components, and so have custom cached, built images for some components.  Setting this option forces rebuilds of those components.",
    advanced=True)
pc.defineParameter(
    "installONFSDRAN","Install ONF SD-RAN RIC",
    portal.ParameterType.BOOLEAN,False,
    longDescription="Install the ONF SD-RAN RIC (https://wiki.opennetworking.org/display/COM/SD-RAN+1.1+Release).  NB: the NexRAN xApp does not work with the SD-RAN RIC at the moment, although our srsLTE RIC agent will connect to the SD-RAN RIC.",
    advanced=True)
pc.defineParameter(
    "buildSrsLTE","Build SrsLTE",
    portal.ParameterType.BOOLEAN,True,
    longDescription="Build and install our version of srsLTE with RIC support.",
    advanced=True)
pc.defineParameter(
    "buildOAI","Build OAI",
    portal.ParameterType.BOOLEAN,False,
    longDescription="Build and install our version of OAI with RIC support.",
    advanced=True)
pc.defineParameter(
    "diskImage","Disk Image",
    portal.ParameterType.IMAGE,
    "urn:publicid:IDN+emulab.net+image+emulab-ops//UBUNTU18-64-STD",
    advanced=True,
    longDescription="An image URN or URL that every node will run.")
pc.defineParameter(
    "multiplexLans", "Multiplex Networks",
    portal.ParameterType.BOOLEAN,False,
    longDescription="Multiplex any networks over physical interfaces using VLANs.  Some physical machines have only a single experiment network interface, so if you want multiple links/LANs, you have to enable multiplexing.  Currently, if you select this option.",
    advanced=True)
pc.defineParameter(
    "createSharedVlan","Create Shared VLAN",
    portal.ParameterType.BOOLEAN,False,
    longDescription="Create a new shared VLAN with the name above, and connect node-0 to it.",
    advanced=True)
pc.defineParameter(
    "connectSharedVlan","Shared VLAN Name",
    portal.ParameterType.STRING,"",
    longDescription="Connect `node-0` to a shared VLAN.  This allows your O-RAN experiment to connect to another experiment.  If the shared VLAN does not yet exist (e.g. was not manually created for you by an administrator, or created in another experiment), enable the next option to create it.",
    advanced=True)
pc.defineParameter(
    "sharedVlanAddress","Shared VLAN IP Address",
    portal.ParameterType.STRING,"10.254.254.1/255.255.255.0",
    longDescription="Set the IP address and subnet mask for the shared VLAN interface.  Make sure you choose an unused address within the subnet of an existing shared vlan!  Also ensure that you specify the subnet mask as a dotted quad.",
    advanced=True)

pc.defineParameter(
    "kubesprayRepo","Kubespray Git Repository",
    portal.ParameterType.STRING,
    "https://github.com/kubernetes-incubator/kubespray.git",
    longDescription="Do not change this value unless you know what you are doing!  Changing would only be necessary if you have a modified fork of Kubespray.  This must be a publicly-accessible repository.",
    advanced=True)
pc.defineParameter(
    "kubesprayVersion","Kubespray Version",
    portal.ParameterType.STRING,"release-2.16",
    longDescription="A tag or commit-ish value; we will run `git checkout <value>`.  The default value is the most recent stable value we have tested.  You should only change this if you need a new feature only available on `master`, or an old feature from a prior release.  We support versions back to release-2.13 only.",
    advanced=True)
pc.defineParameter(
    "kubesprayUseVirtualenv","Kubespray VirtualEnv",
    portal.ParameterType.BOOLEAN,True,
    longDescription="Select if you want Ansible installed in a python virtualenv; deselect to use the system-packaged Ansible.",
    advanced=True)
pc.defineParameter(
    "kubeVersion","Kubernetes Version",
    portal.ParameterType.STRING,"",
    longDescription="A specific release of Kubernetes to install (e.g. v1.16.3); if left empty, Kubespray will choose its current stable version and install that.  You can check for Kubespray-known releases at https://github.com/kubernetes-sigs/kubespray/blob/release-2.16/roles/download/defaults/main.yml (or if you're using a different Kubespray release, choose the corresponding feature release branch in that URL).  You can use unsupported or unknown versions, however, as long as the binaries actually exist.",
    advanced=True)
pc.defineParameter(
    "helmVersion","Helm Version",
    portal.ParameterType.STRING,"",
    longDescription="A specific release of Helm to install (e.g. v2.12.3); if left empty, Kubespray will choose its current stable version and install that.  Note that the version you pick must exist as a tag in this Docker image repository: https://hub.docker.com/r/lachlanevenson/k8s-helm/tags .",
    advanced=True)
pc.defineParameter(
    "dockerVersion","Docker Version",
    portal.ParameterType.STRING,"",
    longDescription="A specific Docker version to install; if left empty, Kubespray will choose its current stable version and install that.  As explained in the Kubespray documentation (https://github.com/kubernetes-sigs/kubespray/blob/master/docs/vars.md), this value must be one of those listed at, e.g. https://github.com/kubernetes-sigs/kubespray/blob/release-2.13/roles/container-engine/docker/vars/ubuntu-amd64.yml .",
    advanced=True)
pc.defineParameter(
    "dockerOptions","Dockerd Options",
    portal.ParameterType.STRING,"",
    longDescription="Extra command-line options to pass to dockerd.  The most common option is probably an --insecure-registry .",
    advanced=True)
pc.defineParameter(
    "doLocalRegistry","Create Private, Local Registry",
    portal.ParameterType.BOOLEAN,True,
    longDescription="Create a private Docker registry on the kube master, and expose it on the (private) management IP address, port 5000, and configure Kubernetes to be able to use it (--insecure-registry).  This is nearly mandatory for some development workflows, so it is on by default.",
    advanced=True)
pc.defineParameter(
    "kubeNetworkPlugin","Kubernetes Network Plugin",
    portal.ParameterType.STRING,"calico",
    [("calico","Calico"),("flannel","Flannel"),("weave","Weave"),
     ("canal","Canal")],
    longDescription="Choose the primary kubernetes network plugin.",
    advanced=True)
pc.defineParameter(
    "kubeEnableMultus","Enable Multus Network Meta Plugin",
    portal.ParameterType.BOOLEAN,False,
    longDescription="Select to enable the Multus (https://github.com/kubernetes-sigs/kubespray/blob/master/docs/multus.md) CNI meta plugin.  Multus provides multiple network interface support to pods.",
    advanced=True)
pc.defineParameter(
    "kubeProxyMode","Kube Proxy Mode",
    portal.ParameterType.STRING,"ipvs",
    [("iptables","iptables"),("ipvs","ipvs")],
    longDescription="Choose the mode for kube-proxy (comparison: https://www.projectcalico.org/comparing-kube-proxy-modes-iptables-or-ipvs/).",
    advanced=True)
pc.defineParameter(
    "kubePodsSubnet","Kubernetes Pods Subnet",
    portal.ParameterType.STRING,"10.233.0.0/16",
    longDescription="The subnet containing pod addresses.",
    advanced=True)
pc.defineParameter(
    "kubeServiceAddresses","Kubernetes Service Addresses",
    portal.ParameterType.STRING,"10.96.0.0/12",
    longDescription="The subnet containing service addresses.",
    advanced=True)
pc.defineParameter(
    "kubeDoMetalLB","Kubespray Enable MetalLB",
    portal.ParameterType.BOOLEAN,True,
    longDescription="We enable MetalLB by default, so that users can use an \"external\" load balancer service type.  You need at least one public IP address for this option because it doesn't make sense without one.",
    advanced=True)
pc.defineParameter(
    "publicIPCount", "Number of public IP addresses",
    portal.ParameterType.INTEGER,1,
    longDescription="Set the number of public IP addresses you will need for externally-published services (e.g., via a load balancer like MetalLB.",
    advanced=True)
pc.defineParameter(
    "kubeFeatureGates","Kubernetes Feature Gate List",
    portal.ParameterType.STRING,"[SCTPSupport=true]",
    longDescription="A []-enclosed, comma-separated list of features.  For instance, `[SCTPSupport=true]`.",
    advanced=True)
pc.defineParameter(
    "kubeletCustomFlags","Kubelet Custom Flags List",
    portal.ParameterType.STRING,"[--allowed-unsafe-sysctls=net.*]",
    longDescription="A []-enclosed, comma-separated list of flags.  For instance, `[--allowed-unsafe-sysctls=net.*]`.",
    advanced=True)
pc.defineParameter(
    "kubeletMaxPods","Kubelet Max Pods",
    portal.ParameterType.INTEGER,120,
    longDescription="An integer max pods limit; 0 allows Kubernetes to use its default value (currently is 110; see https://kubespray.io/#/docs/vars and look for `kubelet_max_pods`).  Do not change this unless you know what you are doing.",
    advanced=True)
pc.defineParameter(
    "kubeAllWorkers","Kube Master is Worker",
    portal.ParameterType.BOOLEAN,False,
    longDescription="Allow the kube master to be a worker in the multi-node case (always true for single-node clusters); disabled by default.",
    advanced=True)
pc.defineParameter(
    "sslCertType","SSL Certificate Type",
    portal.ParameterType.STRING,"self",
    [("none","None"),("self","Self-Signed"),("letsencrypt","Let's Encrypt")],
    advanced=True,
    longDescription="Choose an SSL Certificate strategy.  By default, we generate self-signed certificates, and only use them for a reverse web proxy to allow secure remote access to the Kubernetes Dashboard.  However, you may choose `None` if you prefer to arrange remote access differently (e.g. ssh port forwarding).  You may also choose to use Let's Encrypt certificates whose trust root is accepted by all modern browsers.")
pc.defineParameter(
    "sslCertConfig","SSL Certificate Configuration",
    portal.ParameterType.STRING,"proxy",
    [("proxy","Web Proxy")],
    advanced=True,
    longDescription="Choose where you want the SSL certificates deployed.  Currently the only option is for them to be configured as part of the web proxy to the dashboard.")
pc.defineParameter(
    "doNFS","Enable NFS",
    portal.ParameterType.BOOLEAN,True,
    longDescription="We enable NFS by default, to be used by persistent volumes in Kubernetes services.",
    advanced=True)
pc.defineParameter(
    "nfsAsync","Export NFS volume async",
    portal.ParameterType.BOOLEAN,False,
    longDescription="Force the default NFS volume to be exported `async`.  When enabled, clients will only be given asynchronous write behavior even if they request sync or write with sync flags.  This is dangerous, but some applications that rely on persistent storage cannot be configured to use more helpful sync options (e.g., fsync instead of O_DIRECT).  It will give you the absolute best performance, however.",
    advanced=True)

#
# Get any input parameter values that will override our defaults.
#
params = pc.bindParameters()

if params.publicIPCount > 8:
    perr = portal.ParameterWarning(
        "You cannot request more than 8 public IP addresses, at least not without creating your own modified version of this profile!",
        ["publicIPCount"])
    pc.reportWarning(perr)
if params.kubeDoMetalLB and params.publicIPCount < 1:
    perr = portal.ParameterWarning(
        "If you enable MetalLB, you must request at least one public IP address!",
        ["kubeDoMetalLB","publicIPCount"])
    pc.reportWarning(perr)

# Handle shared vlan address param.
(sharedVlanAddress,sharedVlanNetmask) = (None,None)
if params.sharedVlanAddress:
    aa = params.sharedVlanAddress.split('/')
    if len(aa) != 2:
        perr = portal.ParameterError(
            "Invalid shared VLAN address!",
            ['sharedVlanAddress'])
        pc.reportError(perr)
        pc.verifyParameters()
    else:
        (sharedVlanAddress,sharedVlanNetmask) = (aa[0],aa[1])

#
# Give the library a chance to return nice JSON-formatted exception(s) and/or
# warnings; this might sys.exit().
#
pc.verifyParameters()

#
# General kubernetes instruction text.
#
kubeInstructions = \
  """
## Waiting for your Experiment to Complete Setup

Once the initial phase of experiment creation completes (disk load and node configuration), the profile's setup scripts begin the complex process of installing software according to profile parameters, so you must wait to access software resources until they complete.  The Kubernetes dashboard link will not be available immediately.  There are multiple ways to determine if the scripts have finished.
  - First, you can watch the experiment status page: the overall State will say \"booted (startup services are still running)\" to indicate that the nodes have booted up, but the setup scripts are still running.
  - Second, the Topology View will show you, for each node, the status of the startup command on each node (the startup command kicks off the setup scripts on each node).  Once the startup command has finished on each node, the overall State field will change to \"ready\".  If any of the startup scripts fail, you can mouse over the failed node in the topology viewer for the status code.
  - Third, the profile configuration scripts send emails: one to notify you that profile setup has started, and another notify you that setup has completed.
  - Finally, you can view [the profile setup script logfiles](http://{host-node-0}:7999/) as the setup scripts run.  Use the `admin` username and the automatically-generated random password `{password-adminPass}` .  This URL is available very quickly after profile setup scripts begin work.

## Kubernetes credentials and dashboard access

Once the profile's scripts have finished configuring software in your experiment, you'll be able to visit [the Kubernetes Dashboard WWW interface](https://{host-node-0}:8080/api/v1/namespaces/kube-system/services/https:kubernetes-dashboard:/proxy/#!/login) (approx. 10-15 minutes for the Kubernetes portion alone).

The easiest login option is to use token authentication.  (Basic auth is configured if available, for older kubernetes versions, username `admin` password `{password-adminPass}`.  You may also supply a kubeconfig file, but we don't provide one that includes a secret by default, so you would have to generate that.)

For `token` authentication: copy the token from http://{host-node-0}:7999/admin-token.txt (username `admin`, password `{password-adminPass}`) (this file is located on `node-0` in `/local/setup/admin-token.txt`).

(To provide secure dashboard access, we run a `kube-proxy` instance that listens on localhost:8888 and accepts all incoming hosts, and export that via nginx proxy listening on `{host-node-0}:8080`.  We also create an `admin` `serviceaccount` in the `default` namespace, and that is the serviceaccount associated with the token auth option mentioned just above.)

Kubernetes credentials are in `~/.kube/config`, or in `/root/.kube/config`, as you'd expect.

## Changing your Kubernetes deployment

The profile's setup scripts are automatically installed on each node in `/local/repository`, and all of the Kubernetes installation is triggered from `node-0`.  The scripts execute as your uid, and keep state and downloaded files in `/local/setup/`.  The scripts write copious logfiles in that directory; so if you think there's a problem with the configuration, you could take a quick look through these logs on the `node-0` node.  The primary logfile is `/local/setup/setup-driver.log`.

Kubespray is a collection of Ansible playbooks, so you can make changes to the deployed kubernetes cluster, or even destroy and rebuild it (although you would then lose any of the post-install configuration we do in `/local/repository/setup-kubernetes-extra.sh`).  The `/local/repository/setup-kubespray.sh` script installs Ansible inside a Python 3 `virtualenv` (in `/local/setup/kubespray-virtualenv` on `node-0`).  A `virtualenv` (or `venv`) is effectively a separate part of the filesystem containing Python libraries and scripts, and a set of environment variables and paths that restrict its user to those Python libraries and scripts.  To modify your cluster's configuration in the Kubespray/Ansible way, you can run commands like these (as your uid):

1. "Enter" (or access) the `virtualenv`: `. /local/setup/kubespray-virtualenv/bin/activate`
2. Leave (or remove the environment vars from your shell session) the `virtualenv`: `deactivate`
3. Destroy your entire kubernetes cluster: `ansible-playbook -i /local/setup/inventories/emulab/inventory.ini /local/setup/kubespray/remove-node.yml -b -v --extra-vars "node=node-0,node-1,node-2"`
   (note that you would want to supply the short names of all nodes in your experiment)
4. Recreate your kubernetes cluster: `ansible-playbook -i /local/setup/inventories/emulab/inventory.ini /local/setup/kubespray/cluster.yml -b -v`

To change the Ansible and playbook configuration, you can start reading Kubespray documentation:
  - https://github.com/kubernetes-sigs/kubespray/blob/master/docs/getting-started.md
  - https://github.com/kubernetes-sigs/kubespray
  - https://kubespray.io/
"""

#
# Customizable area for forks.
#
tourDescription = \
  "This profile creates a Kubernetes cluster and installs the O-RAN SC Near-RT RIC (and optionally, the ONF SD-RAN RIC) and xApps.  When you click the Instantiate button, you'll be presented with a list of parameters that you can change to configure your O-RAN and Kubernetes deployments.  Before creating any experiments, read the Instructions, and the parameter documentation."

oranHeadInstructions = \
  """
## Instructions

This profile can be used to deploy an O-RAN instance to connect to RAN resources (e.g. SDRs); to try O-RAN and our srsLTE/OAI RIC agents and xApp; and to develop and test the O-RAN platform and xApps.  You'll want to briefly read the Kubernetes section below to undestand how to access the Kubernetes cluster in your experiment.  Then you can read the O-RAN section further down for a guide to running demos on O-RAN.  This is a complex profile that installs Kubernetes, O-RAN, and xApps (some components built from source) atop a bare Ubuntu image.  This will take about 25 minutes on a `d740`, or 45 minutes on a `d430`.  You cannot immediately begin running demos; first make sure that you can access the Kubernetes dashboard and check that all RIC namespaces/pods/deployments are present and have succeeded.

## General Information

Software used in this profile/demo setup:

  * Fork of srsLTE with O-RAN support: https://gitlab.flux.utah.edu/powderrenewpublic/srslte-ric
  * Our NexRAN RAN-slicing etc xApp: https://gitlab.flux.utah.edu/powderrenewpublic/nexran
  * Fork of scp-kpimon metrics xApp with bugfixes: https://gitlab.flux.utah.edu/powderrenewpublic/ric-scp-kpimon
  * O-RAN: https://wiki.o-ran-sc.org/display/GS/Getting+Started
  * (optionally) SD-RAN: https://wiki.opennetworking.org/display/COM/SD-RAN+1.1+Release

## Connecting to Other Experiments with RAN Resources

(If you just want to run demos in simulated RAN mode, skip this section.  However, if you want to connect RAN resources (POWDER software-defined radios) to O-RAN for live over-the-air testing, it may be useful to create a single O-RAN experiment, and to later create one or more experiments containing RAN resources and connect them to your O-RAN experiment.  To do this, please read the documentation for the shared vlan parameters.  You'll create a shared vlan with the O-RAN experiment first, then later create RAN experiments that are told to connect to that shared vlan.  Make sure to use a random-ish shared vlan name; that secret could allow other experiments to join yours.  Finally, if you don't already have a RAN resource profile, you can start a simple NodeB/2 UE experiment to test over-the-"air" using the POWDER emulator, via this profile: https://www.powderwireless.net/p/PowderTeam/srslte-shvlan-oran .  This profile is configured specifically to connect to an O-RAN experiment, and includes instructions, so it's a good example if you are planning to connect another existing profile to an O-RAN experiment.)

"""

oranTailInstructions = \
  """

## O-RAN

We deploy O-RAN primarily using [its install scripts](http://gerrit.o-ran-sc.org/r/it/dep), making minor modifications where necessary.  The profile gives you many options to change versions of specific components that are interesting to us, but not all combinations work -- O-RAN is under heavy development.

The install scripts create three Kubernetes namespaces: `ricplt`, `ricinfra`, and `ricxapp`.  The platform components are deployed in the former namespace, and xApps are deployed in the latter.

### RAN slicing demo

These instructions take you through you a demo of the interaction between our RAN slicing xApp, the RIC core, and an srsLTE RAN node (with RIC support).  You'll open several ssh connections to the node in your experiment so that you can deploy xApps and monitor the flow of information through the O-RAN RIC components.  If you're more interested in the overall demo, and less so in the gory details, you can skip the (optional) steps.  (You can also fire up a KPM metrics xApp written by Samsung with our bugfixes, and watch metrics arrive from the NodeB each second, as well; those instructions are in the next section.)

(*Note:* if your POWDER account does not have `bash` nor `sh` set as its default shell, run `bash` first, since some of the demo commands use Bourne shell syntax for setting variables.)

#### Viewing component log output:

1. (optional)  In a new ssh connection to `node-0`:
```
kubectl logs -f -n ricplt -l app=ricplt-e2term-alpha
```
(to view the output of the RIC E2 termination service, to which RAN nodes connect over SCTP).

2. (optional)  In a new ssh connection to `node-0`:
```
kubectl logs -f -n ricplt -l app=ricplt-submgr
```
(to view the output of the RIC subscription manager service, which aggregates xApp subscription requests and forwards them to target RAN nodes)

3. (optional) In a new ssh connection to `node-0`:
```
kubectl logs -f -n ricplt -l app=ricplt-e2mgr
```
(to view the output of the RIC E2 manager service, which shows information about connected RAN nodes)

4. (optional) In a new ssh connection to `node-0`:
```
kubectl logs -f -n ricplt -l app=ricplt-appmgr
```
(to view the output of the RIC application manager service, which controls xApp deployment/lifecycle)

5. (optional) In a new ssh connection to `node-0`:
```
kubectl logs -f -n ricplt -l app=ricplt-rtmgr
```
(to view the output of the RIC route manager, which manages RMR routes across the RIC components)


### Running the `nexran` RAN slicing demo:

This demo runs srsLTE in simulated mode with a single UE.  This may not sound exciting from a RAN slicing standpoint, but because our slice scheduler has a toggleable work conserving mode, you can observe the effects of dynamic slice resource reconfiguration with a TCP stream to a single UE, and it's a bit easier to set up.

#### Starting simulated EPC/NodeB/UE(s)

(NB: if you have RAN resources in another experiment, you will most likely want to run both the EPC and NodeB near those RAN resources, and only deploy xApps using these demo instructions.  In that case, you would only need the part of Step 2 below that collects the `E2TERM_SCTP` environment variable.  Then you'll need to add a route from connected RAN experiments over the shared vlan to that IP address, which is within a virtual network inside Kubernetes.)

1. In a new ssh connection to `node-0`, run an srsLTE EPC:
```
sudo /local/setup/srslte-ric/build/srsepc/src/srsepc --spgw.sgi_if_addr=192.168.0.1
```

2. In a new ssh connection to `node-0`, run an srsLTE eNodeB.
```
export E2TERM_SCTP=`kubectl get svc -n ricplt --field-selector metadata.name=service-ricplt-e2term-sctp-alpha -o jsonpath='{.items[0].spec.clusterIP}'`
sudo /local/setup/srslte-ric/build/srsenb/src/srsenb \
    --enb.n_prb=15 --enb.name=enb1 --enb.enb_id=0x19B --rf.device_name=zmq \
    --rf.device_args="fail_on_disconnect=true,id=enb,base_srate=23.04e6,tx_port=tcp://*:2000,rx_port=tcp://localhost:2001" \
    --ric.agent.remote_ipv4_addr=${E2TERM_SCTP} --log.all_level=warn --ric.agent.log_level=debug --log.filename=stdout \
    --slicer.enable=1 --slicer.workshare=0
```
The first line grabs the current E2 termination service's SCTP IP endpoint address (its kubernetes pod IP -- note that there is a different IP address for the E2 term service's HTTP endpoint); then, the second line runs an srsLTE eNodeB in simulated mode, which will connect to the E2 termination service.  If all goes well, within a few seconds, you will see XML message dumps of the E2SetupRequest (sent by the eNodeB) and the E2SetupResponse (sent by the E2 manager, and relayed to the eNodeB by the E2 termination service).
(NB: the first srsenb argument changes the available PRBs because when simulating we have everything on a single node, want to support older hardware, and absolute RAN performance is not the goal of this demo.)
(NB: the final argument disables the default work-conserving behavior for the slice scheduler, so even if UEs bound to one slice do not fully use their allocated resources for a given TTI, those resources are *not* made available to other slices.  This allows us to experiment with dynamic slice resource allocation and observe changes to a single TCP stream and UE.)

3.  In a new ssh connection to `node-0`, run a simulated UE, placing its network interface into a separate network namespace:
```
sudo ip netns add ue1
sudo /local/setup/srslte-ric/build/srsue/src/srsue \
    --rf.device_name=zmq --rf.device_args="tx_port=tcp://*:2001,rx_port=tcp://localhost:2000,id=ue,base_srate=23.04e6" \
    --usim.algo=xor --usim.imsi=001010123456789 --usim.k=00112233445566778899aabbccddeeff --usim.imei=353490069873310 \
    --log.all_level=warn --log.filename=stdout --gw.netns=ue1
```
Note that we place the UE's mobile network interface in separate network namespace since the SPGW network interface from the EPC process is already in the root network namespace with an `192.168.0.1` address in the same subnet as the UE's address will be in.
Note that the IMSI and key correspond to values for `ue1` in `/etc/srslte/user_db.csv`.  If you want to change the contents of that file, make sure to first kill the EPC process, then modify, then restart EPC.  The EPC process updates this file when it exits.

#### Running the NexRAN xApp

1.  In a new ssh connection to `node-0`, onboard and deploy the `nexran` xApp:
    - Onboard the `nexran` xApp:
    ```
    export KONG_PROXY=`kubectl get svc -n ricplt -l app.kubernetes.io/name=kong -o jsonpath='{.items[0].spec.clusterIP}'`
    curl -L -X POST \
        "http://${KONG_PROXY}:32080/onboard/api/v1/onboard/download" \
        --header 'Content-Type: application/json' \
        --data-binary "@/local/profile-public/nexran-onboard.url"
    ```
    (Note that the profile created `/local/profile-public/nexran-onboard.url`, a JSON file that points the onboarder to the xApp config file, and started an nginx endpoint to serve content (the xApp config file) on `node-0:7998`.  The referenced config file is in `/local/profile-public/nexran-config-file.json`.)
    - Verify that the app was successfully created:
    ```
    curl -L -X GET \
        "http://${KONG_PROXY}:32080/onboard/api/v1/charts"
    ```
    (You should see a single JSON blob that refers to a Helm chart.)
    - Deploy the `nexran` xApp:
    ```
    curl -L -X POST \
        "http://${KONG_PROXY}:32080/appmgr/ric/v1/xapps" \
        --header 'Content-Type: application/json' \
        --data-raw '{"xappName": "nexran"}'
    ```
    - View the logs of the `nexran` xApp:
    ```
    kubectl logs -f -n ricxapp -l app=ricxapp-nexran
    ```
    (This shows the output of the `nexran` xApp, including debug messages as slicing commands are sent to the xApp, which passes them down to the targeted NodeB.)

2.  In a new ssh connection to `node-0`, collect the IP address of the `nexran` northbound RESTful interface (so that you can send API invocations via `curl`).  This is the terminal you will use to run the demo driver script.
```
export NEXRAN_XAPP=`kubectl get svc -n ricxapp --field-selector metadata.name=service-ricxapp-nexran-rmr -o jsonpath='{.items[0].spec.clusterIP}'` ; echo $NEXRAN_XAPP
```

3.  Make sure you can talk to the `nexran` xApp:
```
curl -i -X GET http://${NEXRAN_XAPP}:8000/v1/version ; echo ; echo
```
(You should see some version/build info, formatted as a JSON document.)

4.  In a new ssh connection to `node-0`, run an iperf server *in the UE's network namespace* (so that you can observe the effects of dynamic slicing in the downlink:
```
sudo ip netns exec ue1 iperf -s -p 5010 -i 4 -t 36000
```

5.  In a new ssh connection to `node-0`, run an iperf client:
```
iperf -c 192.168.0.2 -p 5010 -i 4 -t 36000
```
You should see a bandwidth of approximately 35-40Mbps on a `d740` with 15 PRBs; but the important thing is to observe the baseline.  By default, unsliced UEs can utilize all available downlink PRBs.

6.  Run the simple demo script.  (This script creates two slices, `fast` and `slow`, where `fast` is given a proportional share of `1024` (the max, range is `1-1024`), and `slow` is given a share of `256`.
```
/local/repository/run-nexran-demo.sh
```
You will see several API invocations, and their return output, scroll past, each prefixed with a message indicating the intent of the invocation.  You should see the client bandwidth drop to around 29Mbps.  This happens because the `fast` slice now has an 80% share of the available bandwidth, and work-conserving mode is disable, so the scheduler is leaving 20% of the PRBs available for UEs bound to the `slow` slice.

7.  Invert the priority of the `fast` and `slow` slices:
```
curl -i -X PUT -H "Content-type: application/json" -d '{"allocation_policy":{"type":"proportional","share":1024}}' http://${NEXRAN_XAPP}:8000/v1/slices/slow ; echo ; echo ;
curl -i -X PUT -H "Content-type: application/json" -d '{"allocation_policy":{"type":"proportional","share":256}}' http://${NEXRAN_XAPP}:8000/v1/slices/fast ; echo ; echo
```
You should see the client bandwidth drop further, to around 7Mbps.

8.  Equalize the priority of the `fast` slice to match the modified `slow` slice:
```
curl -i -X PUT -H "Content-type: application/json" -d '{"allocation_policy":{"type":"proportional","share":1024}}' http://${NEXRAN_XAPP}:8000/v1/slices/fast ; echo ; echo
```
You should see the client bandwidth increase to around 18Mbps, because now both slices are allocated a 50% share.

### KPM (metrics) demo

1. In a new ssh connection to `node-0`, run the following commands to onboard and deploy the `scp-kpimon` xApp:
    - Onboard the `scp-kpimon` xApp:
    ```
    export KONG_PROXY=`kubectl get svc -n ricplt -l app.kubernetes.io/name=kong -o jsonpath='{.items[0].spec.clusterIP}'`
    curl -L -X POST \
        "http://${KONG_PROXY}:32080/onboard/api/v1/onboard/download" \
        --header 'Content-Type: application/json' \
        --data-binary "@/local/profile-public/scp-kpimon-onboard.url"
    ```
    (Note that the profile created `/local/profile-public/scp-kpimon-onboard.url`, a JSON file that points the onboarder to the xApp config file, and started an nginx endpoint to serve content (the xApp config file) on `node-0:7998`.  The referenced config file is in `/local/profile-public/scp-kpimon-config-file.json`.  Note that this config file has an environment variable, `ranList=enB_macro_001_001_0019b0`, that tells kpimon to subscribe to the gNodeB with the args you created above.  If you change the `srsenb` command above with a different mcc/mnc/id, you will need to change the value of this variable and delete and re-create the xApp.  Or if you can figure a way to override an environment variable during xApp deploy, do that.)
    - Verify that the app was successfully created:
    ```
    curl -L -X GET \
        "http://${KONG_PROXY}:32080/onboard/api/v1/charts"
    ```
    (You should see a single JSON blob that refers to a Helm chart.)
    - Deploy the `scp-kpimon` xApp:
    ```
    curl -L -X POST \
        "http://${KONG_PROXY}:32080/appmgr/ric/v1/xapps" \
        --header 'Content-Type: application/json' \
        --data-raw '{"xappName": "scp-kpimon"}'
    ```
    - View the logs of the `scp-kpimon` xApp:
    ```
    kubectl logs -f -n ricxapp -l app=ricxapp-scp-kpimon
    ```
    (This shows the output of the RIC `scp-kpimon` application, which will consist of attempts to subscribe to a target RAN node's key performance metrics, and display incoming indications --- metric reports.  However, to see the decoded metrics, you have to run the following command within the pod, since those logs are not dumped to console.)

4. Stop the prior `kubectl logs ...` command from Step 3, and run
```
kubectl exec -it -n ricxapp `kubectl get pod -n ricxapp -l app=ricxapp-scp-kpimon -o jsonpath='{.items[0].metadata.name}'` -- tail -F /opt/kpimon.log
```
This will show the decoded metric reports as they arrive from the eNodeB.  We have not yet started a UE, so the reports will not initially have much content, and you'll see that `NumberOfActiveUEs` is `0`.  Note that the command is complicated because you must explicitly name a pod to `kubectl exec`, and pod names have random characters in them.  Thus, if you re-dploy the xApp, the pod name will change; hence the embedded command to find the pod name.

5.  (if you already stopped the iperfs from the slicing demo, or skipped it) In a new ssh connection to `node-0`, send some simple traffic from the simulated UE:
```
sudo ip netns exec ue1 ping 192.168.0.1
```
Now you should be seeing "real" performance metrics in the `kpimon` logfile tail process you started in Step 9, like
```
[qSkipTool]2020/10/13 23:31:09 control.go:127: Received message type: 12050
[qSkipTool]2020/10/13 23:31:09 control.go:158: RIC Indication message from {enB_macro_661_8112_0019b0} received
[qSkipTool]2020/10/13 23:31:09 control.go:159: RequestID: 123
[qSkipTool]2020/10/13 23:31:09 control.go:160: RequestSequenceNumber: 17
[qSkipTool]2020/10/13 23:31:09 control.go:161: FunctionID: 0
[qSkipTool]2020/10/13 23:31:09 control.go:162: ActionID: 0
[qSkipTool]2020/10/13 23:31:09 control.go:163: IndicationSN: 7
[qSkipTool]2020/10/13 23:31:09 control.go:164: IndicationType: 0
[qSkipTool]2020/10/13 23:31:09 control.go:165: IndicationHeader: 0866c118
[qSkipTool]2020/10/13 23:31:09 control.go:166: IndicationMessage: 01040000024000000066c11800000000100066c1184a000050100866c1180001600000ac000060071034be1033b4
[qSkipTool]2020/10/13 23:31:09 control.go:167: CallProcessID: 
[qSkipTool]2020/10/13 23:31:09 control.go:181: -----------RIC Indication Header-----------
[qSkipTool]2020/10/13 23:31:09 control.go:183: RIC Indication Header Format: 1
[qSkipTool]2020/10/13 23:31:09 control.go:186: GlobalKPMnodeIDType: 0
[qSkipTool]2020/10/13 23:31:09 control.go:268: PlmnID: 66c118
[qSkipTool]2020/10/13 23:31:09 control.go:327: -----------RIC Indication Message-----------
[qSkipTool]2020/10/13 23:31:09 control.go:328: StyleType: 4
[qSkipTool]2020/10/13 23:31:09 control.go:330: RIC Indication Message Format: 1
[qSkipTool]2020/10/13 23:31:09 control.go:334: PMContainerCount: 3
[qSkipTool]2020/10/13 23:31:09 control.go:345: PMContainer[0]: 
[qSkipTool]2020/10/13 23:31:09 control.go:352: PFContainerType: 1
[qSkipTool]2020/10/13 23:31:09 control.go:355: oDU PF Container: 
[qSkipTool]2020/10/13 23:31:09 control.go:360: CellResourceReportCount: 1
[qSkipTool]2020/10/13 23:31:09 control.go:363: CellResourceReport[0]: 
[qSkipTool]2020/10/13 23:31:09 control.go:367: nRCGI.PlmnID: 66c118
[qSkipTool]2020/10/13 23:31:09 control.go:368: nRCGI.nRCellID: 0000000010
[qSkipTool]2020/10/13 23:31:09 control.go:380: TotalofAvailablePRBsDL: -1
[qSkipTool]2020/10/13 23:31:09 control.go:381: TotalofAvailablePRBsUL: -1
[qSkipTool]2020/10/13 23:31:09 control.go:389: ServedPlmnPerCellCount: 1
[qSkipTool]2020/10/13 23:31:09 control.go:392: ServedPlmnPerCell[0]: 
[qSkipTool]2020/10/13 23:31:09 control.go:396: PlmnID: 
[qSkipTool]2020/10/13 23:31:09 control.go:345: PMContainer[1]: 
[qSkipTool]2020/10/13 23:31:09 control.go:352: PFContainerType: 2
[qSkipTool]2020/10/13 23:31:09 control.go:444: oCU-CP PF Container: 
[qSkipTool]2020/10/13 23:31:09 control.go:452: NumberOfActiveUEs: 1
[qSkipTool]2020/10/13 23:31:09 control.go:345: PMContainer[2]: 
[qSkipTool]2020/10/13 23:31:09 control.go:352: PFContainerType: 3
[qSkipTool]2020/10/13 23:31:09 control.go:454: oCU-UP PF Container: 
[qSkipTool]2020/10/13 23:31:09 control.go:463: CU-UP PF Container Item Count: 1
[qSkipTool]2020/10/13 23:31:09 control.go:466: CU-UP PF Container Item [0]: 
[qSkipTool]2020/10/13 23:31:09 control.go:470: InterfaceType: 2
[qSkipTool]2020/10/13 23:31:09 control.go:473: CU-UP Plmn Count: 1
[qSkipTool]2020/10/13 23:31:09 control.go:476: CU-UP Plmn [0]: 
[qSkipTool]2020/10/13 23:31:09 control.go:480: PlmnID: 66c118
[qSkipTool]2020/10/13 23:31:09 control.go:556: PerQCIReportCount: 2
[qSkipTool]2020/10/13 23:31:09 control.go:559: PerQCIReport[0]: 
[qSkipTool]2020/10/13 23:31:09 control.go:563: QCI: 0
[qSkipTool]2020/10/13 23:31:09 control.go:566: PDCPBytesDL: 00ac
[qSkipTool]2020/10/13 23:31:09 control.go:569: PDCPBytesUL: 00
[qSkipTool]2020/10/13 23:31:09 control.go:559: PerQCIReport[1]: 
[qSkipTool]2020/10/13 23:31:09 control.go:563: QCI: 7
[qSkipTool]2020/10/13 23:31:09 control.go:566: PDCPBytesDL: 34be
[qSkipTool]2020/10/13 23:31:09 control.go:569: PDCPBytesUL: 33b4
```
You should see that `NumberOfActiveUEs` is now `1`, and you should see `PDCPBytes` numbers in both the uplink and downlink, for multiple QCI values.  Note that these byte counters are per-measurement period, and as of this time of writing, the measurement period the kpimon app requests is 1024ms.

### Undeploying and Redeploying Apps (e.g. to re-run demos)

1. To run the demo again if you like, stop the EPC/eNodeB/UE via Ctrl-C.  Wait for the UE process to die before restarting the eNodeB.  You can redeploy xApps via
```
kubectl -n ricxapp rollout restart deployment ricxapp-nexran
kubectl -n ricxapp rollout restart deployment ricxapp-scp-kpimon
```
(If you re-run the commands to access the log output of these containers too quickly, you will get a message that the container is still waiting to start.  Just run it until you see log output.)

8. To undeploy the xApps, you can run
```
export APPMGR_HTTP=`kubectl get svc -n ricplt --field-selector metadata.name=service-ricplt-appmgr-http -o jsonpath='{.items[0].spec.clusterIP}'`
curl -L -X DELETE http://${APPMGR_HTTP}:8080/ric/v1/xapps/nexran
curl -L -X DELETE http://${APPMGR_HTTP}:8080/ric/v1/xapps/scp-kpimon
```

9. To remove the xApp descriptors (e.g. to re-upload with new images or configuration):
```
export ONBOARDER_HTTP=`kubectl get svc -n ricplt --field-selector metadata.name=service-ricplt-xapp-onboarder-http -o jsonpath='{.items[0].spec.clusterIP}'`
curl -L -X DELETE "http://${ONBOARDER_HTTP}:8080/api/charts/nexran/0.1.0"
curl -L -X DELETE "http://${ONBOARDER_HTTP}:8080/api/charts/scp-kpimon/1.0.1"
```

### Redeploying O-RAN (if necessary)

If you want to change anything about your O-RAN deployment, or if a component has failed during a multi-day run, you can run the following commands.  (Note that you can edit `example_recipe.yaml` first if you want to change the version of any of the O-RAN containers, or bits of their configuration.)
```
cd /local/setup/oran/dep/bin
./undeploy-ric-platform
./deploy-ric-platform -f ../../example_recipe.yaml
for ns in ricplt ricinfra ricxapp ; do kubectl get pods -n $ns ; kubectl wait pod -n $ns --for=condition=Ready --all; done
```
After the pods in each RIC namespace are ready (the commands in the `for` loop complete successfully), you can re-run the demo.  Note that you must reset all the environment variables that were initialized in previous steps because O-RAN container and service IP addresses will have changed.

## SD-RAN

There are basic instructions for deploying and testing SD-RAN 1.1 here:  .  We follow their deployment guide, except that we install the SD-RAN umbrella chart in the `sd-ran` Kubernetes namespace, so you will need to modify their example commands accordingly.  To connect our RIC-enabled srsLTE, you will need to run `srsenb` slightly differently than for O-RAN SC:

```
export E2TERM_SCTP=`kubectl get service -n sd-ran onos-e2t -o jsonpath='{.spec.clusterIP}'`
sudo /local/setup/srslte-ric/build/srsenb/src/srsenb \
    --enb.n_prb=15 --enb.name=enb1 --enb.enb_id=0x19B --rf.device_name=zmq \
    --rf.device_args="fail_on_disconnect=true,id=enb,base_srate=23.04e6,tx_port=tcp://*:2000,rx_port=tcp://localhost:2001" \
    --ric.agent.remote_ipv4_addr=${E2TERM_SCTP} \
    --ric.agent.local_port=59596 --ric.agent.local_ipv4_addr=192.168.128.1 \
    --log.all_level=warn --ric.agent.log_level=debug --log.filename=stdout \
    --slicer.enable=1 --slicer.workshare=0
```

You should see a successful E2Setup procedure in the output of `srsenb`, and you can use the SD-RAN instructions to list the e2t connections and see the srsLTE NodeB:

```
kubectl exec -it deploy/onos-cli -- /bin/bash
source <(onos completion bash)
onos e2t list connections
```
"""

tourInstructions = oranHeadInstructions + kubeInstructions + oranTailInstructions

#
# Setup the Tour info with the above description and instructions.
#  
tour = IG.Tour()
tour.Description(IG.Tour.TEXT,tourDescription)
tour.Instructions(IG.Tour.MARKDOWN,tourInstructions)
rspec.addTour(tour)

datalans = []

if params.nodeCount > 1:
    datalan = RSpec.LAN("datalan-1")
    if params.linkSpeed > 0:
        datalan.bandwidth = int(params.linkSpeed)
    if params.multiplexLans:
        datalan.link_multiplexing = True
        datalan.best_effort = True
        # Need this cause LAN() sets the link type to lan, not sure why.
        datalan.type = "vlan"
    datalans.append(datalan)

nodes = dict({})

sharedvlan = None
for i in range(0,params.nodeCount):
    nodename = "node-%d" % (i,)
    node = RSpec.RawPC(nodename)
    if params.nodeType:
        node.hardware_type = params.nodeType
    if params.diskImage:
        node.disk_image = params.diskImage
    j = 0
    for datalan in datalans:
        iface = node.addInterface("if%d" % (j,))
        datalan.addInterface(iface)
        j += 1
    if TBCMD is not None:
        node.addService(RSpec.Execute(shell="sh",command=TBCMD))
    if disableTestbedRootKeys:
        node.installRootKeys(False, False)
    nodes[nodename] = node
    if i == 0 and params.connectSharedVlan:
        iface = node.addInterface("ifSharedVlan")
        if sharedVlanAddress:
            iface.addAddress(
                RSpec.IPv4Address(sharedVlanAddress,sharedVlanNetmask))
        sharedvlan = RSpec.Link('shared-vlan')
        sharedvlan.addInterface(iface)
        if params.createSharedVlan:
            sharedvlan.createSharedVlan(params.connectSharedVlan)
        else:
            sharedvlan.connectSharedVlan(params.connectSharedVlan)
        if params.multiplexLans:
            sharedvlan.link_multiplexing = True
            sharedvlan.best_effort = True
if sharedvlan:
    rspec.addResource(sharedvlan)

for nname in nodes.keys():
    rspec.addResource(nodes[nname])
for datalan in datalans:
    rspec.addResource(datalan)

class EmulabEncrypt(RSpec.Resource):
    def _write(self, root):
        ns = "{http://www.protogeni.net/resources/rspec/ext/emulab/1}"
        el = ET.SubElement(root,"%spassword" % (ns,),attrib={'name':'adminPass'})

adminPassResource = EmulabEncrypt()
rspec.addResource(adminPassResource)

#
# Grab a few public IP addresses.
#
apool = IG.AddressPool("node-0",params.publicIPCount)
try:
    apool.Site("1")
except:
    pass
rspec.addResource(apool)

pc.printRequestRSpec(rspec)
