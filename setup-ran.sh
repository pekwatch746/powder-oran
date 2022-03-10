#!/bin/sh

set -x

export SRC=`dirname $0`
cd $SRC
. $SRC/setup-lib.sh

if [ -f $OURDIR/setup-ran-done ]; then
    echo "setup-ran already ran; not running again"
    exit 0
fi

#logtstart "ran"

if [ "$BUILDSRSLTE" = "1" ]; then
    $SRC/setup-srslte.sh
fi
if [ "$BUILDOAI" = "1" ]; then
    $SRC/setup-oai.sh
fi

#logtend "ran"

touch $OURDIR/setup-ran-done

exit 0
