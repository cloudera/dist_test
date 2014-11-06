#!/usr/bin/python

import os, sys
import subprocess
import pprint

if len(sys.argv) != 4:
    print sys.argv[0], "<dist root> <output folder> <test list>"
    sys.exit(1)

dist_root = sys.argv[1]
output_root = sys.argv[2]
test_list_file = sys.argv[3]

tests = open(test_list_file, "r").read().split("\n")

# Find folders with jars and add to the classpath
dist_glob = dist_root + "/target/hadoop-[0-9]*"
cmd="""find %s -name *.jar | sed "s|[^/]*.jar||" | sort -u""" % (dist_glob)
jar_folders = subprocess.check_output(cmd, shell=True).split("\n")[:-1]

# Format this as a classpath too
classpath = [x + "/*" for x in jar_folders]
classpath = ":".join(classpath)

run_test_cmd = "run_junit"
lib_folder = "lib/"
files = [lib_folder, run_test_cmd] + jar_folders

# Write the isolate file

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
