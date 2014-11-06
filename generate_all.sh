#!/bin/bash

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
source $DIR/lib.sh

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
# Symlink in the project-dist directory so it's relative
base=`basename $1`
ln -s $1 $base

#enumerate_tests $1 $tmpfile
touch $tmpfile
$DIR/generate_isolate.py $tmpdir $base/hadoop-dist $tmpdir $tmpfile
