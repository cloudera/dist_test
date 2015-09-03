#!/usr/bin/env python2.7

import os
import sys
import shlex, subprocess
import argparse
import logging

sys.path = [os.path.join(os.path.realpath(os.path.dirname(__file__)), "../python")] + sys.path
from disttest import isolate

def parse_args():
    parser = argparse.ArgumentParser(description="Distributed test runner for JUnit + Maven projects using Isolate.")

    config_filename = ".grind.cfg"
    default_config_location = os.path.join(os.environ['HOME'], config_filename)

    parser.add_argument('-l', '--list-modules',
                        action='store_true',
                        help="Path to file with the list of tests to run, one per line.")

    parser.add_argument('-m', '--module',
                        action='append',
                        help="Run tests for a module. Can be specified multiple times.")

    parser.add_argument('-i', '--include-pattern',
                        action='append',
                        help="Include pattern for unittests. Can be specified multiple times.")

    parser.add_argument('-e', '--exclude-pattern',
                        action='append',
                        help="Exclude pattern for unittests. Takes precedence over include patterns. Can be specified multiple times.")

    parser.add_argument('-d', '--dry-run',
                        action='store_true',
                        help="Do not actually run tests.")

    parser.add_argument('-v', '--verbose',
                        action='store_true',
                        help="Whether to print verbose output for debugging.")

    parser.add_argument('-c', '--config-file',
                        nargs=1,
                        default=default_config_location,
                        help="Location of grind config file (default is %s)" % default_config_location)

    parser.add_argument('-g', '--generate-config-file',
                        action='store_true',
                        help="Print a sample configuration file to stdout.")

    return parser.parse_args(sys.argv[1:])


def main():
    args = parse_args()


if __name__ == "__main__":
    main()
