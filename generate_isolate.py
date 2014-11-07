#!/usr/bin/python

import os, sys
import subprocess
import pprint
import json
from sets import Set

if len(sys.argv) != 4:
    print sys.argv[0], "<base folder> <source repo relative to base> <test list>"
    sys.exit(1)

base_root = sys.argv[1]
source_repo = sys.argv[2]
test_list_file = sys.argv[3]

tests = open(test_list_file, "r").read().split("\n")

# Find folders with jars and add to the classpath

#dist_glob = dist_root + "/target/hadoop-[0-9]*"
#cmd = """cd %s; find %s -name *.jar | sed "s|[^/]*.jar||" | sort -u""" % (base_root, dist_glob)
#jar_folders = subprocess.check_output(cmd, shell=True).split("\n")[:-1]

# Find folders with "target/classes" and "target/test-classes", compilation output

print "Looking for test classes..."
cmd = """cd %s; find %s/ -regextype posix-egrep -regex ".*/(target/classes|target/test-classes)" -type d""" % (base_root, source_repo)
class_folders = subprocess.check_output(cmd, shell=True).split("\n")[:-1]

print "Finding dependencies with maven..."
#cmd = """cd %s/%s; mvn dependency:build-classpath""" % (base_root, source_repo)
#mvn_deps = subprocess.check_output(cmd, shell=True)
mvn_deps = open("/home/andrew/dev/hadoop-isolate/dep", "rt").read()
mvn_deps = mvn_deps.split("\n")

jar_set = Set()
jar_split = []

i = 0
while i < len(mvn_deps):
    line = mvn_deps[i]
    if "Dependencies classpath:" in line:
        i += 1
        jar_split += [mvn_deps[i]]
    i += 1

for cp in jar_split:
    for jar in cp.split(":"):
        jar_set.add(jar)

# Prune out tools.jar, it gets picked up by maven
jar_set = [x for x in jar_set if "tools.jar" not in x]

# Make symlinks to all the external maven deps so we have them locally / relatively

thirdparty = base_root + "/thirdparty"
os.mkdir(thirdparty)
for jar in jar_set:
    if jar.endswith(".jar"):
        basename = os.path.basename(jar)
        linkname = thirdparty + "/" + basename
        os.link(jar, linkname)

# Add trailing slashes if not present, these are all folders
class_folders = map(lambda x: x + "/" if not x.endswith("/") else x, class_folders)

# Add lib folder, class folder, thirdparty folder
classpath = []
classpath += class_folders
# Needs * at the end to glob up the jars:w
#
classpath += ["lib/*"]
classpath += ["thirdparty/*"]

run_test_cmd = "run_junit"
files = [run_test_cmd] + class_folders + ["lib/", "thirdparty/"]

# Join it up!
classpath_string = ":".join(classpath)


# Write the isolate file, parameterized test case

print "Writing isolate files..."

junit_cmd = """%s -cp %s -Dorg.schmant.task.junit4.target=junit_report.xml -Dtest.build.data=build/test/data barrypitman.junitXmlFormatter.Runner <(TESTCLASS)""" % (run_test_cmd, classpath_string)

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
        "dir" : base_root,
        "args" : ["-i", "hadoop.isolate", "-s", test_class + ".isolated", "--extra-variable", "TESTCLASS=%s" % test_class]
    }
    with open(filename, "wt") as out:
        json.dump(gen, out)
