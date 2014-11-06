#!/usr/bin/python

import os, sys
import subprocess
import pprint
import json

if len(sys.argv) != 5:
    print sys.argv[0], "<base folder> <relative dist root> <output folder> <test list>"
    sys.exit(1)

base_root = sys.argv[1]
dist_root = sys.argv[2]
output_root = sys.argv[3]
test_list_file = sys.argv[4]

tests = open(test_list_file, "r").read().split("\n")

# Find folders with jars and add to the classpath
dist_glob = dist_root + "/target/hadoop-[0-9]*"
cmd = """cd %s; find %s -name *.jar | sed "s|[^/]*.jar||" | sort -u""" % (base_root, dist_glob)
jar_folders = subprocess.check_output(cmd, shell=True).split("\n")[:-1]

# Add our lib folder too
jar_folders += ["lib/"]

# Format this as a classpath too
classpath = [x + "/*" for x in jar_folders]
classpath = ":".join(classpath)

run_test_cmd = "run_junit"
files = [run_test_cmd] + jar_folders

# Write the isolate file, parameterized test case

junit_cmd = """%s -cp "%s" -Dorg.schmant.task.junit4.target=junit_report.xml barrypitman.junitXmlFormatter.Runner <(TESTCLASS)""" % (run_test_cmd, classpath)

isolate = {
    'variables': {
        'command': junit_cmd.split(" "),
        'files': files,
    },
}

with open("hadoop.isolate", "wt") as out:
    pprint.pprint(isolate, stream=out)

# Write the per-test json files for batching
for test_class in tests:
    filename = test_class + ".isolated.gen.json"
    gen = {
        "version" : 1,
        "dir" : output_root,
        "args" : ["-i", "hadoop.isolate", "-s", "hadoop.isolated", "--extra-variable", "TESTCLASS=%s" % test_class]
    }
    with open(filename, "wt") as out:
        json.dump(gen, out)
