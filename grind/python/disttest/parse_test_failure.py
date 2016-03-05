# !/usr/bin/env python
#
# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.
#
# This script parses a test log (provided on stdin) and returns
# a summary of the error which caused the test to fail.

import sys
import xml.etree.ElementTree as ET

def consume_rest(line_iter):
  """ Consume and return the rest of the lines in the iterator. """
  return [l.group(0) for l in line_iter]

def consume_until(line_iter, end_re):
  """
  Consume and return lines from the iterator until one matches 'end_re'.
  The line matching 'end_re' will not be returned, but will be consumed.
  """
  ret = []
  for l in line_iter:
    line = l.group(0)
    if end_re.search(line):
      break
    ret.append(line)
  return ret

# Parse log lines and return failure summary formatted as text.
#
# This helper function is part of a public API called from result_server.py
def extract_failure_summary(log_text, name):
  msg = None
  st = None
  stdout = None
  stderr = None
  suite = None

  root = ET.fromstring(log_text)
  (suite_name, case_name) = name.split('#')
  if root.tag == "testsuite":
    suite = root
  else:
    suite = root.find("testsuite")
  if suite is not None:
    for case in suite.getiterator("testcase"):
      if case.get('name') != case_name:
        continue
      error = case.find("error")
      if error is not None:
        st = error.text
        msg = error.get("message")
      failure = case.find("failure")
      if failure is not None:   # TODO
        st = failure.text
        msg = failure.get("type")
      stdout = case.find("system-out")
      if stdout is not None:
        stdout = stdout.text
      stderr = case.find("system-err")
      if stderr is not None:
        stderr = stderr.text

  return (msg, st, stdout, stderr)

def main(argv):
  # local test mode, for debugging etc.
  f = open(argv[1], 'r')
  print extract_failure_summary(f.read(), argv[2])

if __name__ == "__main__":
    main(sys.argv)