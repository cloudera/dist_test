#!/usr/bin/env bash

# Script to run the unittests for this repo

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

cd $DIR
python2.7 -m unittest disttest.test.test
