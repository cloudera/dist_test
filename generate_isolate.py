#!/usr/bin/python

import os, sys
import subprocess
import pprint

if len(sys.argv) != 2:
    print sys.argv[0], "<dist root>"
    sys.exit(1)

dist_root = sys.argv[1]
dist_glob = dist_root + "/target/hadoop-[0-9]*"

# Find folders with jars and add to the classpath
cmd="""find %s -name *.jar | sed "s|[^/]*.jar||" | sort -u""" % (dist_glob)
jar_folders = subprocess.check_output(cmd, shell=True).split("\n")[:-1]

# Format this as a classpath
cmd="""find %s -name *.jar | sed "s|[^/]*.jar|\*|" | sort -u | tr '\n' :""" % (dist_glob)
classpath = jar_folders.replace(
classpath = subprocess.check_output(cmd, shell=True)

#test_class = "org.apache.hadoop.hdfs.server.namenode.TestAddBlock"
test_class = "org.apache.hadoop.fs.TestFileStatus"

run_test_cmd = "run_junit"

junit_cmd = """%s -cp "%s" org.junit.runner.JUnitCore %s""" % (run_test_cmd, classpath, test_class)

# Make the isolate file

files = [run_test_cmd] + jar_folders

isolate = {
    'variables': {
        'command': junit_cmd.split(" "),
        'files': files,
    },
}

pprint.pprint(isolate)
