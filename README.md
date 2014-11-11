Overview
--------

This is a set of scripts that assists in using [isolate](https://code.google.com/p/swarming/wiki/IsolateDesign) to package up JUnit tests to be run remotely, distributed.

This also depends on a few other repositories:

Swarming (which has isolate). Right now we're using Todd's fork, which has some speed improvements:

http://github.mtv.cloudera.com/todd/swarming.client

Todd's distributed testing client/server/slave:

http://github.mtv.cloudera.com/todd/dist_test

Dependencies
------------

* unzip
* Python 2.7+
* Java
* A local dev environment with your project successfully built

Example usage
-------------

1. Check out all the repos specified above
1. Build your project.
1. Generate the isolate file for your tests by pointing the `generate_all.sh` script at your source repo. It looks for normal and test jars under target folders.

        cd hadoop-isolate
        ./generate_all.sh ~/dev/hadoop/trunk/
        # Output like this
        INFO:root:Looking for compiled jars in source repo...
        INFO:root:Finding dependencies with maven...
        INFO:root:Writing isolate files...
        INFO:root:Success! Generated isolate descriptions in /tmp/tmp.JPIqTdTg4j
        /tmp/tmp.JPIqTdTg4j/*.json


1. The last line says where the isolate files were generated, one per unit test. We need to "archive" the dependencies specified in these files to the isolate server. Currently, Todd is running a server on appspot. Let's start by authenticating and pointing ourselves at this server:

        cd swarming.client
        export ISOLATE_SERVER=https://todd-isolate-2.appspot.com
        python auth.py login --service=https://todd-isolate-2.appspot.com

1. Now, let's run `isolate.py batcharchive` to archive all of our test tasks in one go. This can take a while. Note that we specify an outfile to write a unique hash per isolate task.

        ./isolate.py batcharchive --dump-json=/tmp/hashes.json -- /tmp/tmp.JPIqTdTg4j/*.json

1. Now, we transmute the hashes file into another json file used by the `dist_test` client to actually run the tests

        cd hadoop-isolate
        ./parse_for_submit.py /tmp/hashes.json /tmp/run.json

1. Use the client to run the tasks, watch the magic happen.

        cd dist_test
        ./submit.py /tmp/run.json

Tips and tricks
---------------

Setting SWARMING_PROFILE=1 enables profiling for swarming, might help us find bottlenecks to optimize.
