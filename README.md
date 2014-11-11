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
