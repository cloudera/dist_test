#!/bin/bash

set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

#
# Enumerate the JUnit tests in a source folder.
#
# @param SOURCE_DIR, path to source tree, e.g. "/home/andrew/dev/hadoop/trunk"
# @param OUTPUT_PATH, dumps a list of fully-qualified test classes, one per line
#
function enumerate_tests () {
    SOURCE_DIR=$1
    OUTPUT_PATH=$2

    pushd $SOURCE_DIR > /dev/null

    # Clear the output file
    echo -n > $OUTPUT_PATH

    # This is the regex used by Surefire to find and run test classes
    # http://maven.apache.org/surefire/maven-surefire-plugin/examples/inclusion-exclusion.html
    tests=`find . -regextype posix-egrep -regex ".*/(Test.*.java|.*Test.java|.*TestCase.java)"`

    # For each test class, figure out its fully qualified name (e.g. org.apache.hadoop.hdffs.TestDFSUtil)
    # Determine its package, concat with the basename of the file.
    for x in $tests; do
        classname=`basename $x | cut -d "." -f 1`
        prefix=`grep package $x | cut -d " " -f 2 | cut -d ";" -f 1`
        full=`echo ${prefix}.${classname}`
        echo $full >> $OUTPUT_PATH
    done

    popd > /dev/null
}

#
# Main function. Given a source tree, finds the JUnit tests within it,
# sets up a local environment within a temp folder for isolate,
# and generates an isolate file describing the tests to run and how to run them.
#
# @param SOURCE_DIR, path to source tree, e.g. "/home/andrew/dev/hadoop/trunk"
#
function main () {
    if [ "$#" -ne 1 ]; then
        echo "$0 <hadoop root>"
        exit 1
    fi

    SOURCE_DIR=$1
    shift

    # Make a temp dir
    tmpdir=$(mktemp -d)
    testfile=$tmpdir/tests

    # Everything needs to be relative to the temp dir for isolate to work

    # Populate initially with the skeleton contents (JUnit deps)
    cd $tmpdir
    cp -r $DIR/skeleton/* .

    # Symlink in the source dir so it's relative to the temp dir
    # Force a "/" at the end so it resolves the symlink.
    if [[ "$SOURCE_DIR" != */ ]]; then
        SOURCE_DIR="$SOURCE_DIR/"
    fi
    base=`basename $SOURCE_DIR`
    ln -s $SOURCE_DIR source_dir

    # Find the tests within SOURCE_DIR
    enumerate_tests $SOURCE_DIR $testfile
    #echo org.apache.hadoop.hdfs.server.namenode.TestLeaseManager > $testfile

    # Generate the isolate file
    $DIR/generate_isolate.py --base-dir $tmpdir --source-dir-name source_dir --tests-file $testfile
}
