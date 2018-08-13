grind
=====

grind is a dist_test front end for Java Maven+Surefire+JUnit projects.
It scans your project to find test classes and runtime dependencies, creates isolate tasks, and submits them to the dist_test master to run them on the cluster.

grind's interface resembles that of Surefire, meaning you can do test and module-level includes/excludes.
It also supports more advanced functionality like running tests multiple times, and retrying tests if they fail.

When called with the `--artifacts` flag, grind will download and merge the JUnit output from Surefire into a `test-results.xml` file.
This is useful when running grind in a Jenkins environment, since this merged output can be consumed by the Jenkins JUnit plugin.

Dependencies
------------

* unzip
* Python 2.7+
* Java
* A local dev environment with your project successfully built
* Luci, which is an Isolate compatible rewrite in Go (much faster than the original Python implementation). Follow the README for directions as to installing Luci. If you haven't installed a Go program from source before, this can be involved.

        https://github.com/luci/luci-go

Note that luci-go is only compilable using GO 1.4. Compiling with GO 1.5 will result in internal import violation problem. See details at https://docs.google.com/document/d/1e8kOo3r51b2BWtTs_1uADIA5djfXhPT36s6eHVRIvaU/edit.


Example usage
-------------

1. Fulfil the dependencies listed above.
1. Add grind bin folder to your `$PATH`:

        $ export PATH=/path/to/grind/bin:$PATH

1. Set up the grind configuration, using `grind config`. This is used to find the above project dependencies and our internal isolate server. Fill in `dist_test_user` and `dist_test_password` as is appropriate.

        $ grind config --generate --write
        Do you want to write sample config file to /home/andrew/.grind/grind.cfg? (y/N): y
        Wrote sample config file to /home/andrew/.grind/grind.cfg
        $ grind config
        [grind]
        isolate_server = http://isolate.cloudera.org:4242
        dist_test_client_path = ~/dev/dist_test/bin/client
        dist_test_master = http://dist-test.cloudera.org:80/
        isolate_path = ~/dev/dist_test/bin/isolate
        grind_temp_dir = /tmp
        grind_cache_dir = ~/.grind/cache
        dist_test_password = 
        dist_test_user = 

1. cd to your project and build it, e.g.

        $ cd ~/dev/hadoop/trunk
        $ mvn clean package install -DskipTests -Pdist....

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

1. Run the tests with JDK 7 (default is JDK 8)

        $ grind test --java-version 7

See `grind test --help` for more advanced usage instructions.

Global Configuration
-------------

The `grind config` command lets you display your current configuration, or generate a new sample config file. This config file supports the following keys:

* `isolate_server`: The URL of the isolate server where artifacts will be uploaded.
* `dist_test_client_path`: The path to `client.py` within your checked out `dist_test` repository.
* `dist_test_user`: Your username, if the dist test server requires authentication. This can be overridden by the `DIST_TEST_USER` environment variable.
* `dist_test_password`: Your password, if the dist test server requires authentication. This can be overridden by the `DIST_TEST_PASSWORD` environment variable.
* `dist_test_url_timeout`: The timeout value when sending URL requests to the dist-test server. This can be overridden by the `DIST_TEST_URL_TIMEOUT` environment variable.
* `isolate_path`: Path to the isolate binary, this is used to generate the isolate task descriptions
* `grind_temp_dir`: Where grind will keep per-invocation data. This should be on the same hard disk as the `grind_cache_dir` to enable hardlinking.
* `grind_cache_dir`: Where grind will cached per-project dependency sets. This greatly speeds up repeated grind invocations. This should be on the same hard disk as the `grind_cache_dir` to enable hardlinking.
* `maven_settings_file`: Path where maven settings.xml file is located. If not specified, a default settings.xml will be generated.

Running `grind config` will print your current config settings.

To make it easier to get started, `grind config --generate --write` can be used to write a new default config to the default location (`$HOME/.grind/grind.cfg`).

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

##### DIST_TEST_USER and DIST_TEST_PASSWORD

As mentioned above, grind respects the `DIST_TEST_USER` and `DIST_TEST_PASSWORD` environment variables.

##### DIST_TEST_URL_TIMEOUT

The timeout value when sending URL requests to the dist-test server. Defaults to the socket's [global default timeout](https://docs.python.org/2/library/socket.html#socket.getdefaulttimeout).
As mentioned above, grind respects the `DIST_TEST_URL_TIMEOUT` environment variable.

Per-project Configuration
------------

`grind pconfig` is similar to `config`, but used to specify per-project configuration. It has the following keys:

* `empty_dirs`: Specifies empty directories to be created in each `target` directory at test runtime. Some tests expect these directories to exist.
* `file_globs`: Specifies additional test dependencies via a comma-delimited list of Unix-style path globs. These globs are interpreted by Python's [glob.iglob](https://docs.python.org/2/library/glob.html#glob.iglob).
* `file_patterns`: Specifies additional test dependencies via a comma-delimited list of filename patterns. These patterns are interpreted by Python's [fnmatch.fnmatch](https://docs.python.org/2/library/fnmatch.html#fnmatch.fnmatch).
* `artifact_archive_globs`: Specifies test output to upload after a test has run, via comma-delimited Python glob.iglob glob strings. By default, this matches Surefire's test XML output (`**/surefire-reports/TEST-*.xml`), but it can be modified to also upload additional logs.
* `java_version`: Chooses the runtime JDK version. Supported values are 7 or 8, the default is 7.

Like the `grind config` command, `pconfig` will generate a default config to the default location (`./grind_project.cfg`) when invoked via `grind pconfig --generate --write`.

As an example, here is Hadoop's `.grind_project.cfg`. Hadoop tests expect a few extra directories to be created, and we also need to upload the native libraries that are not picked up by the Maven Dependency Plugin.

        [grind]
        artifact_archive_globs = ["**/surefire-reports/TEST-*.xml"]
        empty_dirs = ["test/data", "test-dir", "log"]
        file_globs = []
        file_patterns = ["*.so"]
        java_version = 7

Common issues when onboarding
-----------------------------

Based on experiences onboarding projects like Hadoop and HBase, common issues include the following:

### Accessing test resources from the src/ folder rather than target/

Theoretically, everything needed to run a test is contained in the `target/` folder, including .class files and test resources.
Test resources are files consumed by test cases, things like configuration files, NameNode metadata, etc.
These resources are automatically copied into `target/test-classes` by the [Maven resources plugin](https://maven.apache.org/plugins/maven-resources-plugin/).
The `target/test-classes` folder is normally referenced from the test by a Java System property.

See [HBASE-14588](https://issues.apache.org/jira/browse/HBASE-14588), [HADOOP-12369](https://issues.apache.org/jira/browse/HADOOP-12369), [HADOOP-12367](https://issues.apache.org/jira/browse/HADOOP-12367) for examples.

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

        $ export ISOLATE_SERVER=http://isolate.cloudera.org:4242
        $ ./luci-py/run_isolated.py --auth-method=none --verbose --leak-temp-dir --hash a21ff4f49b208afd9cda89705fef4668c94fe16a
        ...
        WARNING  22749    run_isolated(197): Deliberately leaking /tmp/run_tha_testGvhm8E for later examination

1. If you go into this new temp dir, you'll be able to invoke it the same way grind does. You can modify this temp dir for faster iteration and troubleshooting.

        $ cd /tmp/run_tha_testGvhm8E
        $ ./run_test.sh hadoop-common-project/hadoop-common/pom.xml TestNativeCodeLoader


Comparing Jenkins job test runs
-------------------------------

When migrating an existing Jenkins job using surefire over to grind, it's nice to diff the test sets to make sure that all tests are still being run. To assist with this, you can use the `test_diff` tool provided in grind's bin directory to compare the JUnit test results of Jenkins jobs. Sample invocation:

    test_diff --first http://jenkins.example.com/view/Hadoop/job/Hadoop-HDFS-2.6.0/ --first http://jenkins.example.com/view/Hadoop/job/Hadoop-YARN-2.6.0 --first http://jenkins.example.com/view/Hadoop/job/Hadoop-Common-2.6.0 --first http://jenkins.example.com/view/Hadoop/job/Hadoop-MR-2.6.0 --second http://jenkins.example.com/view/Hadoop/job/Hadoop-All-grind/ --suites

Contributing to grind
---------------------

grind is composed of:

- `disttest`, a Python module that does test enumeration, test packaging, and generating metadata for consumption by `luci`
- `grind`, the CLI command that serves as the user interface for disttest.

See the code comments and docstrings for more detail. `grind` is a good entry point, since it shows how the `disttest` module is used, and how the different projects (`luci`, `dist_test`) fit in.

Use the `run_tests.sh` script to test your changes to `grind`. New contributions should come with a corresponding unit test.
