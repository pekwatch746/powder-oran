#!/bin/sh

set -x

# Grab our libs
. "`dirname $0`/setup-lib.sh"

if [ -f $OURDIR/setup-xapp-kpimon-done ]; then
    exit 0
fi

logtstart "xapp-kpimon"

# kubectl get pods -n ricplt  -l app=ricplt-e2term -o jsonpath='{..status.podIP}'
KONG_PROXY=`kubectl get svc -n ricplt -l app.kubernetes.io/name=kong -o jsonpath='{.items[0].spec.clusterIP}'`
E2MGR_HTTP=`kubectl get svc -n ricplt --field-selector metadata.name=service-ricplt-e2mgr-http -o jsonpath='{.items[0].spec.clusterIP}'`
APPMGR_HTTP=`kubectl get svc -n ricplt --field-selector metadata.name=service-ricplt-appmgr-http -o jsonpath='{.items[0].spec.clusterIP}'`
E2TERM_SCTP=`kubectl get svc -n ricplt --field-selector metadata.name=service-ricplt-e2term-sctp-alpha -o jsonpath='{.items[0].spec.clusterIP}'`
ONBOARDER_HTTP=`kubectl get svc -n ricplt --field-selector metadata.name=service-ricplt-xapp-onboarder-http -o jsonpath='{.items[0].spec.clusterIP}'`
RTMGR_HTTP=`kubectl get svc -n ricplt --field-selector metadata.name=service-ricplt-rtmgr-http -o jsonpath='{.items[0].spec.clusterIP}'`

curl --location --request GET "http://$KONG_PROXY:32080/onboard/api/v1/charts"

#
# Onboard and deploy our modified scp-kpimon app.
#
# There are bugs in the initial version; and we don't have e2sm-kpm-01.02, so
# we handle both those things.
#
cd $OURDIR

if [ -n "$BUILDORANSC" -a "$BUILDORANSC" = "1" ]; then
    git clone https://gitlab.flux.utah.edu/powderrenewpublic/ric-scp-kpimon.git
    cd ric-scp-kpimon
    git checkout revert-to-e2sm-kpm-01.00
    # Build this image and place it in our local repo, so that the onboard
    # file can use this repo, and the kubernetes ecosystem can pick it up.
    $SUDO docker build . --tag $HEAD:5000/scp-kpimon:powder
    $SUDO docker push $HEAD:5000/scp-kpimon:powder
    KPIMON_REGISTRY=${HEAD}.cluster.local:5000
    KPIMON_NAME="scp-kpimon"
    KPIMON_TAG=powder
else
    KPIMON_REGISTRY="gitlab.flux.utah.edu:4567"
    KPIMON_NAME="powder-profiles/oran/scp-kpimon"
    KPIMON_TAG=powder
    $SUDO docker pull ${KPIMON_REGISTRY}/${KPIMON_NAME}:${KPIMON_TAG}
fi

MIP=`getnodeip $HEAD $MGMTLAN`

cat <<EOF >$WWWPUB/scp-kpimon-config-file.json
{
    "json_url": "scp-kpimon",
    "xapp_name": "scp-kpimon",
    "version": "1.0.1",
    "containers": [
        {
            "name": "scp-kpimon-xapp",
            "image": {
                "registry": "${KPIMON_REGISTRY}",
                "name": "${KPIMON_NAME}",
                "tag": "${KPIMON_TAG}"
            }
        }
    ],
    "appenv": { "ranList":"enB_macro_001_001_0019b0" },
    "messaging": {
        "ports": [
            {
                "name": "rmr-data",
                "container": "scp-kpimon-xapp",
                "port": 4560,
                "rxMessages": [ "RIC_SUB_RESP", "RIC_SUB_FAILURE", "RIC_INDICATION", "RIC_SUB_DEL_RESP", "RIC_SUB_DEL_FAILURE" ],
                "txMessages": [ "RIC_SUB_REQ", "RIC_SUB_DEL_REQ" ],
                "policies": [1],
                "description": "rmr receive data port for scp-kpimon-xapp"
            },
            {
                "name": "rmr-route",
                "container": "scp-kpimon-xapp",
                "port": 4561,
                "description": "rmr route port for scp-kpimon-xapp"
            }
        ]
    },
    "rmr": {
        "protPort": "tcp:4560",
        "maxSize": 2072,
        "numWorkers": 1,
        "txMessages": [ "RIC_SUB_REQ", "RIC_SUB_DEL_REQ" ],
        "rxMessages": [ "RIC_SUB_RESP", "RIC_SUB_FAILURE", "RIC_INDICATION", "RIC_SUB_DEL_RESP", "RIC_SUB_DEL_FAILURE" ],
	"policies": [1]
    }
}
EOF
cat <<EOF >$WWWPUB/scp-kpimon-onboard.url
{"config-file.json_url":"http://$MIP:7998/scp-kpimon-config-file.json"}
EOF

if [ -n "$DOKPIMONDEPLOY" -a $DOKPIMONDEPLOY -eq 1 ]; then
    curl -L -X POST \
        "http://$KONG_PROXY:32080/onboard/api/v1/onboard/download" \
        --header 'Content-Type: application/json' \
	--data-binary "@${WWWPUB}/scp-kpimon-onboard.url"

    curl -L -X GET \
        "http://$KONG_PROXY:32080/onboard/api/v1/charts"

    curl -L -X POST \
	"http://$KONG_PROXY:32080/appmgr/ric/v1/xapps" \
	--header 'Content-Type: application/json' \
	--data-raw '{"xappName": "scp-kpimon"}'
fi

logtend "xapp-kpimon"
touch $OURDIR/setup-xapp-kpimon-done

exit 0
