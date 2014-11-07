#!/bin/bash

~/dev/swarming.client/isolate.py batcharchive --dump-json=hashes.json -- $@
