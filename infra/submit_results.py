#!/usr/bin/env python

import argparse
import config
import fnmatch
import os
import socket
import subprocess
from subprocess import PIPE
import urllib
import urllib2
try:
  import simplejson as json
except:
  import json

config = config.Config()
config.ensure_result_server_configured()

def submit_result(params):
  print "submitting result to server:", params
  url = config.DIST_TEST_RESULT_SERVER + "/add_result?" + urllib.urlencode(params)
  results_str = urllib2.urlopen(url).read()
  print results_str

# TODO support submitting a test result file.
# def add_one_result(path):
#   if os.path.isfile(path):
#     args = get_parser().parse_args(['-f', path])
#   elif os.path.isdir(path):
#     args = get_parser().parse_args(['-p', path])
#   else:
#       print "unknown path type", path
#       return
#   add_results(args)

def crawl_job(params):
  print "crawling job(%s) from server." % params['job_id']
  url = config.DIST_TEST_RESULT_SERVER + "/crawl_from_jobid?" + urllib.urlencode(params)
  results_str = urllib2.urlopen(url).read()
  print results_str

def add_results(args):
  params = {}
  if args.jobid:
      params["job_id"] = args.jobid
  else:
      print "Error: no job id given. jobid is required."
      return False

  if args.file is None and args.path is None and args.key is None:
      print "Info: No file / path / key given. Will crawl the job directly from database."
      crawl_job(params)

  if args.taskid:
      params['task_id'] = args.taskid

  if args.hostname:
    params["hostname"] = args.hostname
  else:
    params["hostname"] = socket.gethostname()

  #TODO: cd project root and get git hash
  p = subprocess.Popen(["git", "rev-parse", "HEAD"], stdout=PIPE)
  params['revision'] = p.communicate()[0]
  d1 = subprocess.Popen(["git", "diff", "--quiet"])
  d1.communicate()
  d2 = subprocess.Popen(["git", "diff", "--quiet", "--cached"])
  d2.communicate()
  if d1.returncode != 0 or d2.returncode != 0:
    params['revision'] += "-dirty"

  # TODO: below are all untested and used for now...
  # add all files to result
  if args.file:
    for f in args.file:
        params['test_report'] = os.path.abspath(f)
        submit_result(params)

  # recursively add all TEST-*.xml under path to result
  if args.path:
    for root, dirs, files in os.walk(args.path):
        for f in fnmatch.filter(files, 'TEST-*.xml'):
            params['test_report'] = os.path.abspath(os.path.join(root, f))
            submit_result(params)

  if args.key:
    params["key"] = args.key
    submit_result(params)

  return True

def get_parser():
  parser = argparse.ArgumentParser(description='Submit a test result to the result server.',
                                   epilog="Example: " \
                                   "submit_results.py -k 'key_on_s3' -t 'task_id'")
  parser.add_argument("-i", "--hostname", help='Specifies the hostname that the test was run')
  parser.add_argument("-f", "--file", action="append", help='The test result file(s)')
  parser.add_argument("-t", "--taskid", help='The task id')
  parser.add_argument("-j", "--jobid", help='The job id')
  parser.add_argument("-p", "--path", help='The path under which the test was run')
  parser.add_argument("-k", "--key", help='The key of the file stored in s3')
  return parser

if __name__ == "__main__":
  args = get_parser().parse_args()
  if add_results(args) != True:
    get_parser().print_help()