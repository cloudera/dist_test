#!/usr/bin/env python

import argparse
import sys
from xml.dom import minidom

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


def merge_xunit(in_files, out_file):
  """
  Merges the input files into the specified output file.
  :return: nothing
  """

  if len(in_files) == 0:
    return

  first_in = in_files[0]
  merge_xml = minidom.parse(first_in)
  testsuite = merge_xml.firstChild

  errors = int(_safe_attribute(testsuite, 'errors'))
  failures = int(_safe_attribute(testsuite, 'failures'))
  tests = int(_safe_attribute(testsuite, 'tests'))
  time = float(_safe_attribute(testsuite, 'time').replace(',', ''))
  skipped = int(_safe_attribute(testsuite, 'skipped'))

  to_merge = [x for x in in_files if x != first_in]
  for in_file in to_merge:
    try:
      #print ('Processing %s ' % in_file)
      in_xml = minidom.parse(in_file)
      in_testsuite = in_xml.firstChild

      errors += int(_safe_attribute(in_testsuite, 'errors'))
      failures += int(_safe_attribute(in_testsuite, 'failures'))
      tests += int(_safe_attribute(in_testsuite, 'tests'))
      time += float(_safe_attribute(in_testsuite, 'time').replace(',', ''))
      skipped += int(_safe_attribute(in_testsuite, 'skipped'))

      for test_cases in in_xml.getElementsByTagName('testcase'):
        testsuite.appendChild(test_cases)
    except Exception as e:
      print("Unable to fully process %s: %s" % (in_file, e))

  _safe_set_attribute(testsuite, 'errors', errors)
  _safe_set_attribute(testsuite, 'failures', failures)
  _safe_set_attribute(testsuite, 'tests', tests)
  _safe_set_attribute(testsuite, 'time', time)
  _safe_set_attribute(testsuite, 'skipped', skipped)

  merge_xml.writexml(open(out_file, 'w'))

def _safe_attribute(testsuite, attribute):
  if testsuite.hasAttribute(attribute):
    return testsuite.attributes[attribute].value


def _safe_set_attribute(testsuite, attribute, value):
  if testsuite.hasAttribute(attribute):
    testsuite.attributes[attribute].value = str(value)


if __name__ == '__main__':
  parser = argparse.ArgumentParser(description='Merges one or more xunit style files.',
                                               epilog="Example: " \
          "find ~/test-results -type f -name 'TEST-*.xml' | ./merge.py -o ~/result.xml")

  parser.add_argument("-o", "--outfile", help='Specifies the location of the output')
  parser.add_argument("-i", "--infile", action="append", help='The files to be merged, or passed as stdin')

  args = parser.parse_args()
  in_files = _get_in_files(args)
  out_file = _get_out_file(args, in_files)
  print ('Will merge into %s' % out_file)

  merge_xunit(in_files, out_file)
