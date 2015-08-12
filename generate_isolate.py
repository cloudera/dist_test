#!/usr/bin/python

import os, sys
import subprocess
import pprint
import json
import argparse
import logging
from sets import Set

def parse_args():

    parser = argparse.ArgumentParser(description="Generate an isolate file describing \
                                     how to run JUnit tests in a source repository.")

    parser.add_argument('-b', '--base-dir',
                        required=True,
                        help="Location of the base folder where the isolate file will be built.")
    parser.add_argument('-s', '--source-dir-name',
                        required=True,
                        help="Name of the source directory relative to the base folder, i.e. \"source_dir\".")
    parser.add_argument('-t', '--tests-file',
                        required=True,
                        type=argparse.FileType('r'),
                        help="Path to file with the list of tests to run, one per line.")
    parser.add_argument('-v', '--verbose',
                        action='store_true',
                        help="Whether to print verbose output for debugging.")

    return parser.parse_args(sys.argv[1:])


def main():

    args = parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    tests = args.tests_file.read().split("\n")
    if len(tests) < 1:
        logging.critical("Passed a test file with no tests within it!")
        sys.exit(1)

    base_dir = args.base_dir
    source_repo = args.source_dir_name

    logging.info("Looking for compiled jars in source repo...")
    cmd = """cd %s; find %s/ -name target""" % (base_dir, source_repo)
    cmd_output = subprocess.check_output(cmd, shell=True)

    if len(cmd_output) == 0:
        logging.critical("Could not find any target folders in directory %s/%s", extra=(base_dir, source_repo))
        sys.exit(1)

    possible_target_folders = cmd_output.split("\n")[:-1]

    # Prune for target folders with -sources.jar, -tests.jar, test-sources.jar, likely build artifacts

    target_folders = []
    target_jars = []
    #required_suffix = [".jar", "-sources.jar", "-tests.jar", "-test-sources.jar"]
    required_suffix = [".jar"]

    for target in possible_target_folders:
        path = base_dir + "/" + target
        listing = [f for f in os.listdir(path) if f.endswith(".jar")]
        is_target = True
        for suffix in required_suffix:
            has_suffix = False
            for jar in listing:
                if jar.endswith(suffix):
                    has_suffix = True
                    break
            if not has_suffix:
                is_target = False
                break

        if is_target:
            target_folders.append(target)
            for jar in listing:
                # Prune out javadoc jars, don't need em
                if not jar.endswith("-javadoc.jar"):
                    target_jars.append(target + "/" + jar)

    if len(target_jars) == 0:
        logging.critical("Could not find any candidate jars in target folders. Have you built the project?")
        sys.exit(1)

    logging.info("Finding dependencies with maven...")
    cmd = """cd %s/%s; mvn dependency:build-classpath""" % (base_dir, source_repo)
    mvn_deps = subprocess.check_output(cmd, shell=True)
    # XXX: temporary hack! Use the above for real use
    #mvn_deps = open("/home/andrew/dev/hadoop-isolate/dep", "rt").read()
    mvn_deps = mvn_deps.split("\n")

    jar_set = Set()
    jar_split = []

    # Parse out the lines after "Dependencies classpath"
    i = 0
    while i < len(mvn_deps):
        line = mvn_deps[i]
        if "Dependencies classpath:" in line:
            i += 1
            jar_split += [mvn_deps[i]]
        i += 1

    # Split and add each jar
    for cp in jar_split:
        for jar in cp.split(":"):
            jar_set.add(jar)

    # Prune out tools.jar, it gets picked up by maven
    jar_set = [x for x in jar_set if "tools.jar" not in x]

    # Make symlinks to all the external maven deps so we have them locally / relatively
    thirdparty = base_dir + "/thirdparty"
    os.mkdir(thirdparty)
    for jar in jar_set:
        if jar.endswith(".jar"):
            basename = os.path.basename(jar)
            linkname = thirdparty + "/" + basename
            os.link(jar, linkname)

    # Form up the classpath
    classpath = []

    # Add the jar and test-classes folder to the classpath
    # We add test-classes rather than the test jar since some tests require it to be unzipped
    # This unzipping is done at runtime
    classpath.append("test-classes/")
    #for target in target_folders:
    #    classpath.append(target+"/test-classes/")
    for jar in target_jars:
        if not jar.endswith("-tests.jar") and not jar.endswith("-test-sources.jar"):
            classpath.append(jar)

    # Needs * at the end to glob up the jars
    classpath += ["lib/*"]
    classpath += ["thirdparty/*"]

    # Join it up!
    classpath_string = ":".join(classpath)

    # The file list is simpler to construct, we just push
    run_test_cmd = "run_junit"
    files = [run_test_cmd] + target_jars + ["lib/", "thirdparty/"]

    # Write the isolate file, parameterized test case

    logging.info("Writing isolate files...")

    junit_cmd = """%s -cp %s barrypitman.junitXmlFormatter.Runner <(TESTCLASS)""" % (run_test_cmd, classpath_string)

    isolate = {
        'variables': {
            'command': junit_cmd.split(" "),
            'files': files,
        },
    }

    with open("hadoop.isolate", "wt") as out:
        pprint.pprint(isolate, stream=out)

    # Write the per-test json files for isolate's batcharchive command
    for test_class in tests:
        filename = test_class + ".isolated.gen.json"
        gen = {
            "version" : 1,
            "dir" : base_dir,
            "args" : ["-i", "hadoop.isolate", "-s", test_class + ".isolated", "--extra-variable", "TESTCLASS=%s" % test_class],
            "name" : test_class
        }
        with open(filename, "wt") as out:
            json.dump(gen, out)

    logging.info("Success! Generated isolate descriptions in %s", base_dir)

    print "%s/*.json" % base_dir

if __name__ == "__main__":
    main()
