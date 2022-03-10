#!/bin/sh

set -x

# Grab our libs
. "`dirname $0`/setup-lib.sh"

if [ -f $OURDIR/setup-xapp-nexran-done ]; then
    exit 0
fi

logtstart "xapp-nexran"

# kubectl get pods -n ricplt  -l app=ricplt-e2term -o jsonpath='{..status.podIP}'
KONG_PROXY=`kubectl get svc -n ricplt -l app.kubernetes.io/name=kong -o jsonpath='{.items[0].spec.clusterIP}'`
E2MGR_HTTP=`kubectl get svc -n ricplt --field-selector metadata.name=service-ricplt-e2mgr-http -o jsonpath='{.items[0].spec.clusterIP}'`
APPMGR_HTTP=`kubectl get svc -n ricplt --field-selector metadata.name=service-ricplt-appmgr-http -o jsonpath='{.items[0].spec.clusterIP}'`
E2TERM_SCTP=`kubectl get svc -n ricplt --field-selector metadata.name=service-ricplt-e2term-sctp-alpha -o jsonpath='{.items[0].spec.clusterIP}'`
ONBOARDER_HTTP=`kubectl get svc -n ricplt --field-selector metadata.name=service-ricplt-xapp-onboarder-http -o jsonpath='{.items[0].spec.clusterIP}'`
RTMGR_HTTP=`kubectl get svc -n ricplt --field-selector metadata.name=service-ricplt-rtmgr-http -o jsonpath='{.items[0].spec.clusterIP}'`

curl --location --request GET "http://$KONG_PROXY:32080/onboard/api/v1/charts"

#
# Onboard and deploy our NexRAN xapp.
#
# There are bugs in the initial version; and we don't have e2sm-kpm-01.02, so
# we handle both those things.
#
cd $OURDIR

if [ -n "$BUILDORANSC" -a "$BUILDORANSC" = "1" ]; then
    git clone https://gitlab.flux.utah.edu/powderrenewpublic/nexran.git
    cd nexran
    # Build this image and place it in our local repo, so that the onboard
    # file can use this repo, and the kubernetes ecosystem can pick it up.
    $SUDO docker build . --tag $HEAD:5000/nexran:latest
    $SUDO docker push $HEAD:5000/nexran:latest
    NEXRAN_REGISTRY=${HEAD}.cluster.local:5000
    NEXRAN_NAME="nexran"
    NEXRAN_TAG=latest
else
    NEXRAN_REGISTRY="gitlab.flux.utah.edu:4567"
    NEXRAN_NAME="powder-profiles/oran/nexran"
    NEXRAN_TAG=latest
    $SUDO docker pull ${NEXRAN_REGISTRY}/${NEXRAN_NAME}:${NEXRAN_TAG}
fi


MIP=`getnodeip $HEAD $MGMTLAN`

cat <<EOF >$WWWPUB/nexran-config-file.json
{
    "json_url": "nexran",
    "xapp_name": "nexran",
    "version": "0.1.0",
    "containers": [
        {
            "name": "nexran-xapp",
            "image": {
                "registry": "${NEXRAN_REGISTRY}",
                "name": "${NEXRAN_NAME}",
                "tag": "${NEXRAN_TAG}"
            }
        }
    ],
    "messaging": {
        "ports": [
            {
                "name": "rmr-data",
                "container": "nexran-xapp",
                "port": 4560,
                "rxMessages": [ "RIC_SUB_RESP", "RIC_SUB_FAILURE", "RIC_INDICATION", "RIC_SUB_DEL_RESP", "RIC_SUB_DEL_FAILURE", "RIC_CONTROL_ACK", "RIC_CONTROL_FAILURE" ],
                "txMessages": [ "RIC_SUB_REQ", "RIC_SUB_DEL_REQ", "RIC_CONTROL_REQ" ],
                "policies": [1],
                "description": "rmr receive data port for nexran-xapp"
            },
            {
                "name": "rmr-route",
                "container": "nexran-xapp",
                "port": 4561,
                "description": "rmr route port for nexran-xapp"
            },
            {
                "name": "nbi",
                "container": "nexran-xapp",
                "port": 8000,
                "description": "RESTful http northbound interface nexran-xapp"
            }
        ]
    },
    "rmr": {
        "protPort": "tcp:4560",
        "maxSize": 2072,
        "numWorkers": 1,
        "txMessages": [ "RIC_SUB_REQ", "RIC_SUB_DEL_REQ", "RIC_CONTROL_REQ" ],
        "rxMessages": [ "RIC_SUB_RESP", "RIC_SUB_FAILURE", "RIC_INDICATION", "RIC_SUB_DEL_RESP", "RIC_SUB_DEL_FAILURE", "RIC_CONTROL_ACK", "RIC_CONTROL_FAILURE" ],
	"policies": [1]
    }
}
EOF
cat <<EOF >$WWWPUB/nexran-onboard.url
{"config-file.json_url":"http://$MIP:7998/nexran-config-file.json"}
EOF

if [ -n "$DONEXRANDEPLOY" -a $DONEXRANDEPLOY -eq 1 ]; then
    curl -L -X POST \
        "http://$KONG_PROXY:32080/onboard/api/v1/onboard/download" \
        --header 'Content-Type: application/json' \
	--data-binary "@${WWWPUB}/nexran-onboard.url"

    curl -L -X GET \
        "http://$KONG_PROXY:32080/onboard/api/v1/charts"

    curl -L -X POST \
	"http://$KONG_PROXY:32080/appmgr/ric/v1/xapps" \
	--header 'Content-Type: application/json' \
	--data-raw '{"xappName": "nexran"}'
fi

logtend "xapp-nexran"
touch $OURDIR/setup-xapp-nexran-done

exit 0
