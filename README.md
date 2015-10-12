grind
=====

grind finds the tests in your Java Maven+Surefire+JUnit project, packages them up individually, and runs them distributed across a cluster. Empirically, running the 1700+ test classes in Hadoop has gone from multiple hours to about fifteen minutes by using grind.

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
        grind_cache = ~/.grind/cache
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

1. Run the tests for the entire project

        $ grind test

1. Run the tests for some modules

        $ grind test -m hadoop-hdfs -m hadoop-common

1. Run the tests for specific tests within a module

        $ grind test -m hadoop-hdfs -i TestBalancer\* -i TestDFSClient -i Test\*CLI

See `grind test --help` for more advanced usage instructions.

Common issues when onboarding
-----------------------------

Based on experiences onboarding projects like Hadoop and HBase, common issues include the following:

### Accessing test resources from the src/ folder rather than target/

Theoretically, everything needed to run a test is contained in the `target/` folder, including .class files and test resources.
Test resources are files consumed by test cases, things like configuration files, NameNode metadata, etc.
These resources are automatically copied into `target/test-classes` by the [Maven resources plugin](https://maven.apache.org/plugins/maven-resources-plugin/).
The `target/test-classes` folder is normally referenced from the test by a Java System property.

See [HBASE-14588](https://issues.apache.org/jira/browse/HBASE-14588), [HADOOP-12369](https://issues.apache.org/jira/browse/HBASE-14588), [HADOOP-12367](https://issues.apache.org/jira/browse/HADOOP-12367) for examples.

### No test-sources.jar attached

Test resources are not packaged in the normal .jar, -tests.jar, or -sources.jar. Your project needs to attach a test-sources.jar if your tests need test resources.
This is easily handled via the Maven source plugin, see [HBASE-14587](https://issues.apache.org/jira/browse/HBASE-14587) for an example.

### Tests cannot be invoked via `surefire:test` goal

Grind invokes tests via `mvn surefire:test -Dtest=TestFoo`. Invoking the `surefire:test` goal directly skips the expensive scan and potential recompile of source files.
However, due to the intricacies of Maven configuration, this direct invocation might not work if Surefire also requires other Maven plugins to be run first.
This is an anti-pattern, and can hopefully be avoided with some additional Maven work.

See [HBASE-14586](https://issues.apache.org/jira/browse/HBASE-14586) for an example, where Jacoco was modifying the Surefire argLine.

### Miscellaneous

This just documents some other issues found-and-fixed that you might also run into:

* [HADOOP-12368](https://issues.apache.org/jira/browse/HADOOP-12368). Some tests picked up by Grind's test pattern did not actually have any tests inside, so would always fail when invoked. In this case, these were base tests that were not marked as abstract, and the fix was simply to mark the test class as abstract since grind skips abstract classes.

Contributing to grind
---------------------

grind is composed of:

- `disttest`, a Python module that does test enumeration, test packaging, and generating metadata for consumption by `luci`
- `grind`, the CLI command that serves as the user interface for disttest.

See the code comments and docstrings for more detail. `grind` is a good entry point, since it shows how the `disttest` module is used, and how the different projects (`luci`, `dist_test`) fit in.

Use the `run_tests.sh` script to test your changes to `disttest`. New contributions should come with a corresponding unit test.
