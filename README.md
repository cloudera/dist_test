Overview
--------

This is a set of scripts that assists in using [isolate](https://code.google.com/p/swarming/wiki/IsolateDesign) to package up JUnit tests to be run remotely, distributed.

Dependencies
------------

* unzip
* Python 2.7+
* Java
* A local dev environment with your project successfully built
* Luci, which is an Isolate compatible rewrite in Go (much faster than the original Python implementation). Follow the README for directions as to installing Luci. If you haven't installed  a Go program from source before, this can be involved.

        https://github.com/luci/luci-go

* dist_test, which is has a client for submitting to our internal distributed test infrastructure:

        http://github.mtv.cloudera.com/todd/dist_test

Example usage
-------------

1. Fulfil the dependencies listed above.
1. Add grind bin folder to your `$PATH`:

        $ export PATH=/path/to/grind/bin:$PATH

1. Set up the grind configuration, using `grind config`. This is used to find the above project dependencies and our internal isolate server.

        $ grind config > ~/.grind.cfg
        $ grind config
        INFO:root:Read config from location /home/andrew/.grind.cfg
        [grind]
        isolate_server = http://a1228.halxg.cloudera.com:4242
        dist_test_client_path = ~/dev/dist_test/client.py
        isolate_path = ~/dev/go/bin/isolate

1. cd to your project and build it, e.g.

        $ cd ~/dev/hadoop/trunk
        $ mvn clean package install -DskipTests....

1. List the available modules, if it's a multi-module project

        $ grind test --list-modules
        ...
        hadoop-hdfs
        hadoop-common
        ...

1. Run the tests for some modules

        $ grind test -m hadoop-hdfs -m hadoop-common

1. Run the tests for specific tests within a module

        $ grind test -m hadoop-hdfs -i TestBalancer\* -i TestDFSClient -i Test\*CLI

See `grind test --help` for more advanced usage instructions.
