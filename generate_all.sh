#!/bin/bash

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
source $DIR/lib.sh

if [ "$#" -ne 2 ]; then
    echo "$0 <hadoop root> <output folder>"
    exit 1
fi

tmpdir=$(mktemp -d)
tmpfile=$tmpdir/tests

cd $DIR

ln -s $1 .
base=`basename $1`

exit

enumerate_tests $1 $tmpfile
./generate_isolate.py $base/hadoop-dist $2 $tmpfile
