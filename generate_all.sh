#!/bin/bash

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
source $DIR/lib.sh

if [ "$#" -ne 2 ]; then
    echo "$0 <hadoop root> <output folder>"
    exit 1
fi

tmpfile=$(mktemp)

echo "Enumerating test cases..."
enumerate_tests $1 $tmpfile

cd $DIR
./generate_isolate.py $1/hadoop-dist $2 $tmpfile
