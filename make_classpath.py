#!/usr/bin/python

import os, sys
import subprocess
import pprint

if len(sys.argv) != 2:
    print sys.argv[0], "<dist root>"
    sys.exit(1)

dist_root = sys.argv[1]

# Find folders with jars and add to the classpath
cmd="""find %s -name *.jar | sed "s|[^/]*.jar||" | sort -u""" % (dist_root)

#print cmd

jar_folders = subprocess.check_output(cmd, shell=True).split("\n")[:-1]

#for x in jar_folders:
#    print x,

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

pprint.pprint(isolate)
