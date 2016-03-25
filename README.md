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
Note that luci-go is only compilable using GO 1.4. Compiling with GO 1.5 will result in internal import violation problem. See details at https://docs.google.com/document/d/1e8kOo3r51b2BWtTs_1uADIA5djfXhPT36s6eHVRIvaU/edit.

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
        grind_temp_dir = /tmp
        grind_cache_dir = ~/.grind/cache

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

Configuration
-------------

`grind config` generates a sample config file, with the following keys:

* `isolate_server`: The URL of the isolate server where artifacts will be uploaded.
* `dist_test_client_path`: The path to `client.py` within your checked out `dist_test` repository.
* `isolate_path`: Path to the isolate binary, this is used to generate the isolate task descriptions
* `grind_temp_dir`: Where grind will keep per-invocation data. This should be on the same hard disk as the `grind_cache_dir` to enable hardlinking.
* `grind_cache_dir`: Where grind will cached per-project dependency sets. This greatly speeds up repeated grind invocations. This should be on the same hard disk as the `grind_cache_dir` to enable hardlinking.

Grind also supports specifying additional per-project dependencies that need to be tracked, relative to module `target` folders.
This is done in a `.grind_deps` JSON file stored in the project root.
As an example, Hadoop creates some empty directories for tests to use which need to be present in the test environment.
Hadoop also builds native libraries which are not included in the JAR, but are also required for test execution.

        {
            "empty_dirs": ["test/data", "test-dir", "log"],
            "file_patterns": ["*.so"]
        }

Richer support for specifying these additional dependencies will be added on demand.

### Environment variables

Grind also allows setting some special configuration via environment variables.

##### GRIND_MAVEN_FLAGS

This allows you to specify profiles and additional properties to Maven.

e.g. `export GRIND_MAVEN_FLAGS='-Pnative -Dmaven.javadoc.skip=true'`.

##### GRIND_MAVEN_REPO

There are times when the project to test is built using the `-Dmaven.repo.local=...` flag that downloads all dependencies to a location other than the default `~/.m2/repository`. 
Grind will invoke `dependency:copy-dependencies`, and it will try to copy all dependencies from the default location. If they're not there, then it will download them again.

`GRIND_MAVEN_REPO` variable will assure to use the specified maven local repository to copy all dependencies to the Grind cache.

e.g. `export GRIND_MAVEN_REPO='/home/user/dependencies/repository'`

**Notice**: You can use `GRIND_MAVEN_FLAGS` to specify the `-Dmaven.repo.local` flag as well, but this will override other Grind invocations that happen locally and on the Grind server, such as `mvn surefire:test`.
This override may cause Grind to fail because the local repository will not exist on the Grind server.

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

Running a unit test locally
---------------------------

When debugging, it's nice to run a test locally. This can be done as follows:

1. Run grind on the test you want to run with `--dry-run --leak-temp`. This skips actually submitting the test tasks, and leaves the intermediate submission metadata in a temp folder.

        $ grind test --dry-run --leak-temp -i TestNativeCodeLoader
        ...
        INFO:__main__:Leaking temp directory /tmp/grind.d5X4RA

1. Look in the temp directory `hashes.json` for the hash which identifies the isolate task.

        $ cat /tmp/grind.d5X4RA/hashes.json
        {
          "org.apache.hadoop.util.TestNativeCodeLoader": "a21ff4f49b208afd9cda89705fef4668c94fe16a"
        }%

1. Run the hash using the isolate client, which will make another temp dir:

        $ export ISOLATE_SERVER=http://a1228.halxg.cloudera.com:4242
        $ ~/dev/swarming/client/run_isolated.py --verbose --leak-temp-dir --hash a21ff4f49b208afd9cda89705fef4668c94fe16a
        ...
        WARNING  22749    run_isolated(197): Deliberately leaking /tmp/run_tha_testGvhm8E for later examination

1. If you go into this new temp dir, you'll be able to invoke it the same way grind does. You can modify this temp dir for faster iteration and troubleshooting.

        $ cd /tmp/run_tha_testGvhm8E
        $ ./run_test.sh hadoop-common-project/hadoop-common/pom.xml TestNativeCodeLoader

Contributing to grind
---------------------

grind is composed of:

- `disttest`, a Python module that does test enumeration, test packaging, and generating metadata for consumption by `luci`
- `grind`, the CLI command that serves as the user interface for disttest.

See the code comments and docstrings for more detail. `grind` is a good entry point, since it shows how the `disttest` module is used, and how the different projects (`luci`, `dist_test`) fit in.

Use the `run_tests.sh` script to test your changes to `disttest`. New contributions should come with a corresponding unit test.
