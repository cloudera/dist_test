#!/usr/bin/env python

import getpass
import logging
import os
import sys
import time
import urllib
import urllib2
import simplejson
import time

TEST_MASTER = "http://a1228.halxg.cloudera.com:8081"

def generate_job_id():
  return "%s.%d.%d" % (getpass.getuser(), int(time.time()), os.getpid())

def watch_results(job_id):
  url = TEST_MASTER + "/job_status?" + urllib.urlencode([("job_id", job_id)])
  start_time = time.time()
  while True:
    result_str = urllib2.urlopen(url).read()
    result = simplejson.loads(result_str)
    print "\x1b[F\x1b[2K",
    run_time = time.time() - start_time
    print "%.1fs\t%d/%d tasks complete (%d failed)" % \
        (run_time,
         result['finished_tasks'], result['total_tasks'], result['failed_tasks'])
    if result['finished_tasks'] == result['total_tasks']:
      break
    time.sleep(0.5)


def main(argv):
  logging.basicConfig(level=logging.INFO)

  job_id = generate_job_id()
  query_string = urllib.urlencode(
    [("job_id", job_id)] +
    [("tasks", t) for t in argv[1:]])
  url = TEST_MASTER + "/submit_tasks?" + query_string
  logging.debug("Submitting to %s" % url)
  result_str = urllib2.urlopen(url).read()
  result = simplejson.loads(result_str)

  watch_url = TEST_MASTER + "/job?" + urllib.urlencode([("job_id", job_id)])
  logging.info("Submitted tasks. Watch your results at %s", watch_url)

  watch_results(job_id)


if __name__ == "__main__":
  main(sys.argv)
