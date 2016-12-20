#!/usr/bin/env python

"""Merges multiple JUnit XML test results into a single file.

This is useful when invoking a test of the same name multiple times,
e.g. when iterating a flaky test. Otherwise, the Jenkins JUnit plugin will not
display each iteration.

This also changes the pass/fail criteria such that a test is only marked as failed
if all of its iterations failed. This is targeted at the flaky test usecase; we want
to ride over flakiness rather than failing the build. Flaky test tracking can happen
via other tools better suited than Jenkins.

This file can be used standalone, or used as a library. See the "--help" output for
command-line usage instructions.

Adapted from http://github.mtv.cloudera.com/QE/infra_tools/blob/master/xunit_merge.py
"""

import argparse
import sys
from xml.dom import minidom
import xml.dom
from collections import defaultdict
import codecs
import logging

logging.basicConfig(format='%(levelname)s:%(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

def _get_in_files(args):
  """
  Get files that should be merged together. The files are either specified on the command line
  using the --input/-i switch. Or piped to
  :param args: parsed argparser arguments
  :return: a list of filenames
  """
  if args.infile:
    files_ = args.infile
  else:
    files_ = [x.strip() for x in sys.stdin]
  return files_


def _get_out_file(args, in_files):
  """
  Get the destination file, which implicitly will be the first (in order) of the input files or
  an explicit file.
  :param args: parsed argparser arguments
  :param in_files: the input files
  :return: the output file
  """
  if args.outfile:
    return args.outfile
  else:
    return in_files[0]


def merge_xunit(in_files, out_file, ignore_flaky=False, quiet=False):
  """
  Merges the input files into the specified output file.
  :param in_files: list of input files
  :param out_file: location to write merged output file
  :param ignore_flaky: whether to ignore flaky test cases
  :param quiet: whether to suppress some prints
  :return: nothing
  """

  if len(in_files) == 0:
    return

  logger.debug("input files are: " + ",".join(in_files))
  logger.debug("output file is: " + out_file)

  first_in = in_files[0]
  open_first_in = codecs.open(first_in, "r", "utf-8")
  xml_string = open_first_in.read().encode("utf-8")
  merge_xml = minidom.parseString(xml_string)
  testsuite = merge_xml.firstChild

  errors = int(_safe_attribute(testsuite, 'errors', 0))
  failures = int(_safe_attribute(testsuite, 'failures', 0))
  num_tests = int(_safe_attribute(testsuite, 'tests', 0))
  time = float(_safe_attribute(testsuite, 'time', "0.0").replace(',', ''))
  skipped = int(_safe_attribute(testsuite, 'skipped'), 0)

  to_merge = [x for x in in_files if x != first_in]

  name2tests = defaultdict(list)
  for in_file in to_merge:
    try:
      if not quiet:
        print ('Processing %s ' % in_file)
      in_xml = minidom.parse(in_file)
      in_testsuite = in_xml.firstChild

      errors += int(_safe_attribute(in_testsuite, 'errors', 0))
      failures += int(_safe_attribute(in_testsuite, 'failures', 0))
      num_tests += int(_safe_attribute(in_testsuite, 'tests', 0))
      time += float(_safe_attribute(in_testsuite, 'time', "0.0").replace(',', ''))
      skipped += int(_safe_attribute(in_testsuite, 'skipped', 0))

      for test_case in in_xml.getElementsByTagName('testcase'):
        name = (_safe_attribute(test_case, "classname"), _safe_attribute(test_case, "name"))
        name2tests[name].append(test_case)
    except Exception as e:
      print("Unable to fully process %s: %s" % (in_file, e))

  # Filter out the failures of flaky tests
  if ignore_flaky:
    for name, tests in name2tests.iteritems():
      # Failed: all failed. This also works for skipped tests, since they'll always skip.
      # Flaky: one pass and one or more failures
      # Succeeded: all passed
      # Failed testcases have child <error> or <failure> nodes.
      # Skipped testscases have a child <skipped/> node.
      failed_list = []
      for test in tests:
        failed = False
        for child in test.childNodes:
          # Only count presence of a child element, want to ignore text nodes
          if child.nodeType == xml.dom.Node.ELEMENT_NODE:
            failed = True
            break
        failed_list.append(failed)
      failed = all(failed_list)
      succeeded = all([not f for f in failed_list])
      # Failure or success, we can pass through
      if failed or succeeded:
        continue
      else:
        # Filter out failed attempts from a flaky run
        succeeded = []
        for test in tests:
          if not test.hasChildNodes():
            # If it succeeded, append to the list
            succeeded.append(test)
          else:
            # Else do not append, and update the global stats
            for child in test.childNodes:
              # Skip everything that's not an element, i.e. <error> or <failure>
              if child.nodeType != xml.dom.Node.ELEMENT_NODE:
                continue
              if child.nodeName == "error":
                errors -= 1
              elif child.nodeName == "failure":
                failures -= 1
              time -= float(_safe_attribute(child, "time", "0.0").replace(',', ''))
              num_tests -= 1
        name2tests[name] = succeeded

  # Populate the output DOM
  for tests in name2tests.values():
    for test in tests:
      testsuite.appendChild(test)

  _safe_set_attribute(testsuite, 'errors', errors)
  _safe_set_attribute(testsuite, 'failures', failures)
  _safe_set_attribute(testsuite, 'tests', num_tests)
  _safe_set_attribute(testsuite, 'time', time)
  _safe_set_attribute(testsuite, 'skipped', skipped)

  merge_xml.writexml(codecs.open(out_file, 'w', encoding="utf-8"),
                     indent="\t", newl="\n", encoding="utf-8")

def _safe_attribute(testsuite, attribute, default=None):
  if testsuite.hasAttribute(attribute):
    return testsuite.attributes[attribute].value
  else:
    return default


def _safe_set_attribute(testsuite, attribute, value):
  if testsuite.hasAttribute(attribute):
    testsuite.attributes[attribute].value = str(value)


if __name__ == '__main__':
  parser = argparse.ArgumentParser(description='Merges one or more xunit style files.',
                                               epilog="Example: " \
          "find ~/test-results -type f -name 'TEST-*.xml' | ./merge.py -o ~/result.xml")

  parser.add_argument("-o", "--outfile", help='Specifies the location of the output')
  parser.add_argument("-i", "--infile", action="append", help='The files to be merged, or passed as stdin')
  parser.add_argument("--ignore-flaky", dest="ignore_flaky", action="store_true", help='Whether to ignore failed attempts of flaky tests.')
  parser.add_argument("-q", "--quiet", dest="quiet", action="store_true", help='Print fewer messages to stdout.')

  args = parser.parse_args()
  in_files = _get_in_files(args)
  out_file = _get_out_file(args, in_files)
  print ('Will merge into %s' % out_file)

  merge_xunit(in_files, out_file, ignore_flaky=args.ignore_flaky, quiet=args.quiet)
