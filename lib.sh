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

function main () {
    if [ "$#" -ne 1 ]; then
        echo "$0 <hadoop root>"
        exit 1
    fi

    tmpdir=$(mktemp -d)
    tmpfile=$tmpdir/tests
    echo "Using tmpdir" $tmpdir

    # Everything needs to be relative to this tmp dir for isolate to work
    # Populate initially with the skeleton contents (isolate deps)
    cd $tmpdir
    cp -r $DIR/skeleton/* .
    # Symlink in the source dir so it's relative
    base=`basename $1`
    ln -s $1 source_repo

    #enumerate_tests $1 $tmpfile
    echo org.apache.hadoop.fs.TestTest > $tmpfile
    touch $tmpfile
    $DIR/generate_isolate.py $tmpdir source_repo $tmpfile
}
