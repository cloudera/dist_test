#!/usr/bin/python

import os, sys
import subprocess

if len(sys.argv) != 2:
    print sys.argv[0], "<project dist root>"
    sys.exit(1)

dist_root = sys.argv[1]
print "Using project dist root", dist_root

# Find folders with jars and add to the classpath
cmd="""find %s -name *.jar | sed "s|[^/]*.jar||" | sort -u""" % (dist_root)

#print cmd

jar_folders = subprocess.check_output(cmd, shell=True).split("\n")[:-1]

print jar_folders

junit_cmd = "java -cp PRODU"

# Make the isolate file

isolate = {
    'variables': {
        'command': [
            'java',
        ],
        'files': jar_folders,
    },
}

print isolate
