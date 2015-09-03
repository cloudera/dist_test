#!/usr/bin/python

import json
import sys

if len(sys.argv) != 3:
    print sys.argv[0], "<json file with hashes> <output json file>"
    sys.exit(1)

# Sample output
outmap = {
    "tasks": [
        {"isolate_hash": "fa0fee63c6d4e540802d22464789c21de12ee8f5",
         "description": "andrew test task"}
    ]
}

tasks = []

inmap = json.load(open(sys.argv[1], "r"))
for k,v in inmap.iteritems():
    tasks += [{"isolate_hash" : str(v),
              "description" : str(k),
              "timeout": 300
             }]

outmap = {"tasks": tasks}

json.dump(outmap, open(sys.argv[2], "wt"))

