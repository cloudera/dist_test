#!/usr/bin/env python

import logging
import re
import subprocess
import time
import urllib2

DIST_TEST_URL = "http://dist-test.cloudera.org"
# GCE bills 10-minute minimum, so if we've started instances
# more recently than 10 minutes ago, we shouldn't shut them down.
SHRINK_LAG = 600

def get_stats():
  page = urllib2.urlopen(DIST_TEST_URL).read()
  m = re.search("Queue length: (\d+).*Running: (\d+)", page, re.DOTALL)
  if not m:
    raise Exception("Bad page content")
  return dict(queue_len=int(m.group(1)), running=int(m.group(2)))

def resize(num_nodes):
  logging.info("Setting num nodes to %d" % num_nodes)
  subprocess.check_call(
     ("gcloud compute instance-groups managed resize " +
     "dist-test-slave-group --size=%d" % num_nodes).split(" "),
     stdout=file("/dev/null", "w"))

def get_target_size():
  output = subprocess.check_output(
    'gcloud compute instance-groups managed describe dist-test-slave-group'.split(" "))
  m = re.search('targetSize: (\d+)', output)
  return int(m.group(1))
    

def main():
  logging.basicConfig(level=logging.INFO)
  last_size = get_target_size()
  logging.info("initial size: %d" % last_size)
  last_grow_time = 0
  while True:
    try:
      stats = get_stats()
      logging.info(stats)
      new_size = last_size
      if stats['queue_len'] > 0:
        new_size = min(100, last_size + 10)
        last_grow_time = time.time()
      elif stats['queue_len'] + stats['running'] == 0 and \
           time.time() - last_grow_time > SHRINK_LAG:
        new_size = 1
      if new_size != last_size:
        resize(new_size)
        last_size = new_size
    except Exception, e:
      logging.warning("had error" + repr(e))
    time.sleep(10)


if __name__ == "__main__":
  main()
