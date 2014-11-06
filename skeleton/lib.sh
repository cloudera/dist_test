#!/bin/bash

set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

function enumerate_tests () {
    pushd $1

    tests=`find . -regextype posix-egrep -regex ".*/(Test.*.java|.*Test.java|.*TestCase.java)"`

    for x in $tests; do
        classname=`basename $x | cut -d "." -f 1`
        prefix=`grep package $x | cut -d " " -f 2 | cut -d ";" -f 1`
        full=`echo ${prefix}.${classname}`
        echo $full >> $2
    done

    popd
}
