# Reference materials:
#   https://code.google.com/p/swarming/wiki/IsolateDesign
#   https://code.google.com/p/swarming/wiki/IsolatedDesign
#
# We use the Swarming / Isolate / Luci infrastructure from Chromium.
# We're responsible for generating ".isolate" files, which specify
# the command to run and the environment. Luci takes the isolate files
# and generates ".isolated" files, which can then be submitted
# and executed on a distributed testing cluster.
#`
# Since each test is basically the same as the others in terms of dependencies
# and how they are invoked, we can use "batch archive" rather than "archive"
# which is a more efficient way of invoking Luci.
# The isolate file is parameterized with the test name and anything else.
# A separate isolated.gen.json file then specifies the different parameters.
#
# Excerpted from the docs:
#
# A .isolate file is a python file (not JSON!) that contains a single dict
# instance. The allowed items are:
#
#     includes: list of .isolate files to include, i.e. that will be processed
#               before processing this file.
#     variables: dict of variables. Only 3 variables are allowed:
#         command: list that describes the command to run, i.e. each argument.
#         files: list of dependencies to track, i.e. files and directories.
#         read_only: an integer of value 0, 1 or 2. 1 is the default.
#             0 means that the tree is created writeable. Any file can be
#               opened for write and modified.
#             1 means that all the files have the write bit removed (or read
#               only bit set on Windows) so that the file are not writeable
#               without modifying the file mode. This may be or not be
#               enforced by other means.
#             2 means that the directory are not writeable, so that no file
#               can even be added. Enforcement can take different forms but
#               the general concept is the same, no modification, no creation.
#     conditions: list of GYP conditions, so that the content of each
#                 conditions applies only if the condition is True. Each
#                 condition contains a single set of variables.
#
# Each dependency entry can be a file or a directory. If it is a directory,
# it must end with a '/'. Otherwise, it must not end with a '/'. '\' must not
# be used.
import os
import stat
import logging
import pprint
import json

import mavenproject, packager

logger = logging.getLogger(__name__)

class Isolate:

    __RUN_SCRIPT_NAME = """run_test.sh"""
    __RUN_SCRIPT_CONTENTS = """#!/usr/bin/env bash
. /opt/toolchain/toolchain.sh
M2_REPO=$(pwd)/.m2/repository mvn surefire:test -f $1 -Dtest=$2"""

    __COMMAND = """%s <(POM) <(TESTCLASS)""" % __RUN_SCRIPT_NAME

    __ISOLATE_NAME = """disttest.isolate"""

    def __init__(self, project_root, output_dir):
        logger.info("Using output directory " + output_dir)
        print output_dir
        self.output_dir = output_dir
        self.maven_project = mavenproject.MavenProject(project_root)
        self.packager = packager.Packager(self.maven_project, self.output_dir)

    def package(self):
        self.packager.package_target_dirs()
        self.packager.package_maven_dependencies()

    def generate(self):
        # Write the test runner script
        run_path = os.path.join(self.output_dir, self.__RUN_SCRIPT_NAME)
        with open(run_path, "wt") as out:
            out.write(self.__RUN_SCRIPT_CONTENTS)
        os.chmod(run_path, 0755)

        # Write the parameterized isolate file
        files = self.packager.get_relative_output_paths()
        isolate = {
            'variables': {
                'command': self.__COMMAND.split(" "),
                'files': files,
            },
        }
        isolate_path = os.path.join(self.output_dir, self.__ISOLATE_NAME)
        with open(isolate_path, "wt") as out:
            pprint.pprint(isolate, stream=out)

        # Write the per-test json files for isolate's batcharchive command
        for module, classes in self.maven_project.get_modules_to_classes().iteritems():
            abs_pom = os.path.join(module, "pom.xml")
            rel_pom = os.path.relpath(abs_pom, self.maven_project.project_root)
            for c in classes:
                test_class = os.path.basename(c)
                if test_class.endswith(".class"):
                    test_class = test_class[:-len(".class")]
                filename = os.path.join(self.output_dir, "%s.isolated.gen.json" % test_class)
                args = ["-i", self.__ISOLATE_NAME, "-s", test_class + ".isolated"]
                extra_args = {
                    "POM" : rel_pom,
                    "TESTCLASS" : test_class,
                }
                for k,v in extra_args.iteritems():
                    args += ["--extra-variable", "%s=%s" % (k,v)]
                gen = {
                    "version" : 1,
                    "dir" : self.output_dir,
                    "args" : args,
                    "name" : test_class
                }
                with open(filename, "wt") as out:
                    json.dump(gen, out)

        logger.info("Success! Generated isolate descriptions in %s", self.output_dir)
