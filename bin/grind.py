#!/usr/bin/env python2.7

import os
import json
import sys
import shlex, subprocess
import argparse
import logging
import ConfigParser
import tempfile
import shutil

sys.path = [os.path.join(os.path.realpath(os.path.dirname(__file__)), "../python")] + sys.path
from disttest import isolate

logger = logging.getLogger(__name__)


class Config:

    def __init__(self):
        # Load up the defaults
        FILENAME = ".grind.cfg"
        home = os.environ['HOME']
        self.location = os.path.join(home, FILENAME)
        defaults = {
            "isolate_server": "http://a1228.halxg.cloudera.com:4242",
            "isolate_path": os.path.join(home, "dev", "go", "bin", "isolate"),
            "dist_test_client_path": os.path.join(home, "dev", "dist_test", "client.py"),
        }
        self.config = ConfigParser.SafeConfigParser(defaults)

    def read_config(self):
        if not os.path.exists(self.location):
            raise Exception("No config file found at %s, try --generate first?" % self.location)
        if not os.path.isfile(self.location):
            raise Exception("Config location %s is not a file" % self.location)
        # Reset the config and read it in
        self.config = ConfigParser.SafeConfigParser()
        self.config.read(self.location)
        logging.info("Read config from location %s", self.location)

    def write_config(self, outfile):
        self.config.write(outfile)

class ConfigRunner:
    """Config subcommand."""

    def __init__(self, args):
        self.args = args

    @staticmethod
    def add_subparser(subparsers):
        parser = subparsers.add_parser('config', help="Grind configuration")
        parser.add_argument('-g', '--generate',
                            action='store_true',
                            help="Print a sample configuration file to stdout.")

    def run(self):
        # If generate, print the default config
        if self.args.generate:
            self.write_config(sys.stdout)
            return
        # Else, load and print the found config file
        self.read_config()
        self.write_config(sys.stdout)


class TestRunner:
    """Test subcommand."""

    def __init__(self, args):
        self.args = args
        self.project_dir = os.getcwd()
        self.config = Config()
        self.config.read_config()
        self.output_dir = tempfile.mkdtemp()
        logger.debug("Created temp directory %s", self.output_dir)
        pass

    @staticmethod
    def add_subparser(subparsers):
        parser = subparsers.add_parser('test', help="Running tests")
        # Module related
        # TODO: implement these!
        parser.add_argument('-l', '--list-modules',
                            action='store_true',
                            help="Path to file with the list of tests to run, one per line.")
        parser.add_argument('-m', '--module',
                            action='append',
                            help="Run tests for a module. Can be specified multiple times.")
        # Patterns
        # TODO: implement these!
        parser.add_argument('-i', '--include-pattern',
                            action='append',
                            help="Include pattern for unittests. Can be specified multiple times.")
        parser.add_argument('-e', '--exclude-pattern',
                            action='append',
                            help="Exclude pattern for unittests." \
                            + "Takes precedence over include patterns. Can be specified multiple times.")
        # Util
        parser.add_argument('--leak-temp',
                            action='store_true',
                            help="Leak the temp directory with intermediate files")
        parser.add_argument('--dry-run',
                            action='store_true',
                            help="Do not actually run tests.")

    def run(self):
        i = isolate.Isolate(self.project_dir, self.output_dir)
        # Enumerate tests and package test dependencies
        i.package()
        # Generate one task description json file per test
        i.generate()

        # Set up required environment variables
        isolate_env = os.environ
        isolate_env["ISOLATE_SERVER"] = self.config.isolate_server

        # Invoke batcharchive on the generated files
        cmd = "%s batcharchive --dump-json=%s --"
        hashes_file = os.path.join(self.output_dir, "hashes.json")
        cmd = cmd % (self.config.isolate_path, hashes_file)
        logger.debug("Invoking %s", cmd)
        args = shlex.split(cmd)
        args += i.isolated_files
        p = subprocess.Popen(args, env=isolate_env)
        p.wait()

        if p.returncode != 0:
            raise Exception("isolate batcharchive failed")

        # Parse the dumped json file and turn it into task descriptions
        # for dist_test
        tasks_file = os.path.join(self.output_dir, "run.json")
        TestRunner.isolate_hashes_to_tasks(hashes_file, tasks_file)

        # Call the dist_test client
        if args.dry_run:
            logging.info("Dry run, skipping test submission")
        else:
            cmd = "%s submit %s" % (self.config.dist_test_client_path, tasks_file)
            logger.debug("Calling %s", cmd)
            p = subprocess.Popen(args, env=isolate_env)
            if p.returncode != 0:
                raise Exception("dist_test client submit failed")

        logging.info("Finished running tests!")

    def cleanup(self):
        if self.args.leak_temp:
            logger.info("Leaking temp directory %s", self.output_dir)
        else:
            logger.debug("Removing temp directory %s", self.output_dir)
            shutil.rmtree(self.output_dir)

    @staticmethod
    def isolate_hashes_to_tasks(infile, outfile):
        """Transform the hashes from the isolate batcharchive command into
        another JSON file for consumption by dist_test client that describes
        the set of tasks to run."""

        # Example of what outmap should look like, list of tasks
        # This gets overwritten below
        outmap = {
            "tasks": [
                {"isolate_hash": "fa0fee63c6d4e540802d22464789c21de12ee8f5",
                "description": "andrew test task"}
            ]
        }

        tasks = []

        logger.debug("Reading input json file with isolate hashes from %s", infile)
        with open(infile, "r") as i:
            inmap = json.load(open(i, "r"))
            for k,v in inmap.iteritems():
                tasks += [{"isolate_hash" : str(v),
                        "description" : str(k),
                        "timeout": 300
                        }]

        outmap = {"tasks": tasks}

        logger.debug("Writing output json file with task descriptions to %s", outfile)
        with open(outfile, "wt") as o:
            json.dump(outmap, o)


# Main method and subcommand routing

def main():
    parser = argparse.ArgumentParser(
        description="Distributed test runner for JUnit + Maven projects using Isolate.")

    # Add subparsers from each subcommand
    subparsers = parser.add_subparsers(title='subcommands', dest='subparser_name')
    TestRunner.add_subparser(subparsers)
    ConfigRunner.add_subparser(subparsers)

    # Global argument
    parser.add_argument('-v', '--verbose',
                        action='store_true',
                        help="Whether to print verbose output for debugging.")
    args = parser.parse_args(sys.argv[1:])

    if args.verbose:
        logger.setLevel(logging.DEBUG)

    # Route to the correct subcommand based on subparser_name
    subcommands = {
        "test": test_subcommand,
        "config": config_subcommand,
    }

    subcommands[args.subparser_name](args)


def config_subcommand(args):
    config = ConfigRunner(args)
    config.run()


def test_subcommand(args):

    runner = TestRunner(args)
    try:
        runner.run()
    finally:
        runner.cleanup()


if __name__ == "__main__":
    main()
