#!/usr/bin/env bash

set -e
set -x

if [ -z $1 ]; then
    echo "Need to specify input dir"
    exit 1
fi

export ISOLATE_SERVER=http://a1228.halxg.cloudera.com:4242
rm $1/hashes.json $1/run.json || true
$HOME/dev/go/bin/isolate batcharchive --dump-json=$1/hashes.json -- $1/org.apache.hadoop.hdfs.util.*.json
$HOME/dev/hadoop-isolate/python/disttest/parse_for_submit.py $1/hashes.json $1/run.json
cat $1/run.json
$HOME/dev/dist_test/client.py submit $1/run.json
