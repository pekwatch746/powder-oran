#!/bin/sh

set -x

# Grab our libs
. "`dirname $0`/setup-lib.sh"

if [ -f $OURDIR/setup-oran-done ]; then
    exit 0
fi

logtstart "oran"

mkdir -p $OURDIR/oran
cd $OURDIR/oran

# Login to o-ran docker registry server (both staging and release) so
# that Dockerfile base images can be pulled.
$SUDO docker login -u docker -p docker https://nexus3.o-ran-sc.org:10004
$SUDO docker login -u docker -p docker https://nexus3.o-ran-sc.org:10002
$SUDO chown -R $SWAPPER ~/.docker

#
# The O-RAN build image repo is purged pretty regularly, so re-tag old
# image names to point to the latest thing, to enable old builds.
#
if [ -n "$BUILDORANSC" -a "$BUILDORANSC" = "1" ]; then
    CURRENTIMAGE="nexus3.o-ran-sc.org:10002/o-ran-sc/bldr-ubuntu18-c-go:1.9.0"
    OLDIMAGES="nexus3.o-ran-sc.org:10004/o-ran-sc/bldr-ubuntu18-c-go:1.9.0 nexus3.o-ran-sc.org:10004/o-ran-sc/bldr-ubuntu18-c-go:9-u18.04 nexus3.o-ran-sc.org:10004/o-ran-sc/bldr-ubuntu18-c-go:8-u18.04"

    $SUDO docker pull $CURRENTIMAGE
    for oi in $OLDIMAGES ; do
	$SUDO docker tag $CURRENTIMAGE $oi
    done
fi

#
# Custom-build the O-RAN components we might need.  Bronze release is
# pretty much ok, but there are two components that need upgrades from
# master:
#
# * e2term must not attempt to decode the E2SMs (it only supported
#   E2SM-gNB-NRT when it was decoding them)
# * submgr must not decode the E2SMs.
#
# cherry is ok too, except we still need a 4G enb e2 fix.
#

E2TERM_REGISTRY=${HEAD}.cluster.local:5000
if [ $RICVERSION -eq $RICCHERRY ]; then
    E2TERM_TAG="5.4.8-powder"
elif [ $RICVERSION -eq $RICDAWN ]; then
    E2TERM_TAG="5.4.9-powder"
fi
if [ -n "$BUILDORANSC" -a "$BUILDORANSC" = "1" ]; then
    E2TERM_NAME="e2term"
    git clone https://gitlab.flux.utah.edu/powderrenewpublic/e2
    cd e2
    git checkout ${RICRELEASE}-powder
    #git checkout 3f5c142bdef909687e4634ef5af22b4b280ecddf
    cd RIC-E2-TERMINATION
    $SUDO docker build -f Dockerfile -t ${E2TERM_REGISTRY}/${E2TERM_NAME}:${E2TERM_TAG} .
    $SUDO docker push ${E2TERM_REGISTRY}/${E2TERM_NAME}:${E2TERM_TAG}
    cd ../..
else
    E2TERM_REGISTRY="gitlab.flux.utah.edu:4567"
    E2TERM_NAME="powder-profiles/oran/e2term"
    $SUDO docker pull ${E2TERM_REGISTRY}/${E2TERM_NAME}:${E2TERM_TAG}
fi

if [ $RICVERSION -eq $RICBRONZE ]; then
    git clone https://gerrit.o-ran-sc.org/r/ric-plt/submgr
    cd submgr
    git checkout f0d95262aba5c1d3770bd173d8ce054334b8a162
    $SUDO docker build . -t ${HEAD}.cluster.local:5000/submgr:0.5.0
    $SUDO docker push ${HEAD}.cluster.local:5000/submgr:0.5.0
    cd ..
fi

#
# Deploy the platform.
#
DEPREPO=http://gerrit.o-ran-sc.org/r/it/dep
DEPBRANCH=$RICRELEASE
if [ $RICVERSION -eq $RICCHERRY ]; then
    DEPREPO=https://gitlab.flux.utah.edu/powderrenewpublic/dep
    DEPBRANCH=cherry-powder
elif [ $RICVERSION -eq $RICDAWN ]; then
    DEPREPO=https://gitlab.flux.utah.edu/powderrenewpublic/dep
    DEPBRANCH=dawn-powder
fi
git clone $DEPREPO -b $DEPBRANCH
cd dep
git submodule update --init --recursive --remote
git submodule update

helm init --client-only --stable-repo-url "https://charts.helm.sh/stable"

if [ -e ric-dep/RECIPE_EXAMPLE/example_recipe_oran_${RICRELEASE}_release.yaml ]; then
    cp ric-dep/RECIPE_EXAMPLE/example_recipe_oran_${RICRELEASE}_release.yaml \
       $OURDIR/oran/example_recipe.yaml
else
    cp RECIPE_EXAMPLE/PLATFORM/example_recipe.yaml $OURDIR/oran
fi
cat <<EOF >$OURDIR/oran/example_recipe.yaml-override
e2term:
  alpha:
    image:
      registry: "${E2TERM_REGISTRY}"
      name: "${E2TERM_NAME}"
      tag: "${E2TERM_TAG}"
EOF
if [ $RICVERSION -eq $RICBRONZE ]; then
    cat <<EOF >>$OURDIR/oran/example_recipe.yaml-override
submgr:
  image:
    registry: "${HEAD}.cluster.local:5000"
    name: submgr
    tag: 0.5.0
EOF
elif [ $RICVERSION -eq $RICCHERRY ]; then
    # Cherry release of `dep` includes old broken submgr
    cat <<EOF >>$OURDIR/oran/example_recipe.yaml-override
submgr:
  image:
    registry: "nexus3.o-ran-sc.org:10002/o-ran-sc"
    name: ric-plt-submgr
    tag: 0.5.8
EOF
fi
if [ $RICVERSION -eq $RICCHERRY -o $RICVERSION -eq $RICDAWN ]; then
    # appmgr > 0.4.3 isn't really released yet.
    cat <<EOF >>$OURDIR/oran/example_recipe.yaml-override
appmgr:
  image:
    appmgr:
      registry: "nexus3.o-ran-sc.org:10002/o-ran-sc"
      name: ric-plt-appmgr
      tag: 0.4.3
EOF
fi

yq m --inplace --overwrite $OURDIR/oran/example_recipe.yaml \
    $OURDIR/oran/example_recipe.yaml-override

helm version -c --short | grep -q v3
HELM_IS_V3=$?
if [ $HELM_IS_V3 -eq 0 ]; then
    # Unfortunately, the helm setup is completely intermingled
    # with the chart packaging... and chartmuseum APIs aren't used to upload;
    # just copy files into place.  So we have to do everything manually.
    # They also assume ownership of the helm local repo... we need to work
    # around this eventually, e.g. to co-deploy oran and onap.
    #
    # So for now, we start up the helm servecm plugin ourselves.

    # This becomes root on our behalf :-/
    # NB: we need >= 0.13 so that we can get the version that
    # can restrict bind to localhost.
    #
    # helm servecm will prompt us if helm is not already installed,
    # so do this manually.
    curl -o /tmp/get.sh https://raw.githubusercontent.com/helm/chartmuseum/main/scripts/get-chartmuseum
    bash /tmp/get.sh
    # This script is super fragile w.r.t. extracting version --
    # vulnerable to github HTML format change.  Forcing a particular
    # tag works around it.
    if [ ! $? -eq 0 ]; then
	bash /tmp/get.sh -v v0.13.1
    fi
    helm plugin install https://github.com/jdolitsky/helm-servecm
    eval `helm env | grep HELM_REPOSITORY_CACHE`
    nohup helm servecm --port=8879 --context-path=/charts --storage local --storage-local-rootdir $HELM_REPOSITORY_CACHE/local/ --listen-host localhost 2>&1 >/dev/null &
    sleep 4
fi
cd bin \
    && ./deploy-ric-platform -f $OURDIR/oran/example_recipe.yaml

for ns in ricplt ricinfra ricxapp ; do
    kubectl get pods -n $ns
    kubectl wait pod -n $ns --for=condition=Ready --all
done

$SUDO pkill chartmuseum

logtend "oran"
touch $OURDIR/setup-oran-done
