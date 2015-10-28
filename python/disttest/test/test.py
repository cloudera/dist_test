import fnmatch
import os
import shutil
import shlex, subprocess
import tempfile
import unittest
import json

from .. import mavenproject, packager, isolate, classfile

TEST_RESOURCES = os.path.join(os.path.abspath(os.path.dirname(__file__)), "test-resources")

TEST_PROJECT_PATH = os.path.join(TEST_RESOURCES, "MultiModuleTestProject")

def setUpModule():
    # Build the test project
    cmd = "mvn -q package -DskipTests"
    print "Building test maven project at %s" % TEST_PROJECT_PATH
    args = shlex.split(cmd)
    p = subprocess.Popen(args, cwd=TEST_PROJECT_PATH)
    p.wait()
    if p.returncode != 0:
        raise Exception("Failed to build Maven project")

class TestMavenProject(unittest.TestCase):

    def test_MavenProject(self):
        project = mavenproject.MavenProject(TEST_PROJECT_PATH)
        for module in project.modules:
            if "module-two" in module.root:
                # Expect a test-sources.jar and a tests.jar
                self.assertEquals(2, len(module.test_artifacts))
                found = [False, False]
                for artifact in module.test_artifacts:
                    if artifact.endswith("test-sources.jar"):
                        found[0] = True
                    elif artifact.endswith("tests.jar"):
                        found[1] = True
                self.assertTrue(found[0])
                self.assertTrue(found[1])

    def test_IncludeModules(self):
        include_lists = [
            [],
            ["module-two"],
            ["module-one", "module-three"],
            ["module-one", "module-two", "module-three"],
        ]

        for l in include_lists:
            project = mavenproject.MavenProject(TEST_PROJECT_PATH, l)
            self.assertEquals(len(l), len(project.included_modules))
            for m in project.included_modules:
                self.assertTrue(m.name in l,
                           "Found unexpected module %s for include list %s" % (m.name, l))

        invalid_lists = [
            ["blahmodule"],
            ["blahmodule", "module-two"],
        ]

        for l in invalid_lists:
            try:
                project = mavenproject.MavenProject(TEST_PROJECT_PATH, l)
                self.fail("Should have failed to find nonexistent module list " + l)
            except mavenproject.ModuleNotFoundException:
                pass

    def test_IncludeExcludePatterns(self):
        # list of (([includes], [excludes]), [results])
        expected = [
            ((["*"], None),
                ["TestLinkedListReversal", "TestFailSometimes", "TestHelloWorld", "AppTest"]),
            ((["Test*"], None),
                ["TestLinkedListReversal", "TestFailSometimes", "TestHelloWorld"]),
            ((["*Linked*"], None),
                ["TestLinkedListReversal"]),
            ((["*Test"], None),
                ["AppTest"]),
            ((None, ["Test*"]),
                ["AppTest"]),
            ((None, ["AppTest"]),
                ["TestLinkedListReversal", "TestFailSometimes", "TestHelloWorld"]),
            ((None, ["*"]),
                []),
            ((["Test*"], ["*Reversal", "*Sometimes"]),
                ["TestHelloWorld"]),
            ((["Test*"], ["Test*"]),
                []),
        ]

        for ((include,exclude), results) in expected:
            print include, exclude, results
            project = mavenproject.MavenProject(TEST_PROJECT_PATH, include_patterns=include, exclude_patterns=exclude)
            classes = []
            for module in project.included_modules:
                for test in module.test_classes:
                    classes.append(test.classname)
            classes.sort()
            results.sort()
            self.assertEqual(results, classes)

class TestFilters(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.temp)

    def test_NoAbstractClassFilter(self):
        noabs_filter = mavenproject.NoAbstractClassFilter()
        # Test some abstract and concrete classes
        num_files = 0
        for root, dirs, files in os.walk(os.path.join(TEST_RESOURCES, "classes/")):
            for f in files:
                fullpath = os.path.realpath(os.path.join(root, f))
                clazz = classfile.Classfile(fullpath)
                if root.endswith("abstract"):
                    self.assertFalse(noabs_filter.accept(clazz), "Path %s is abstract!" % fullpath)
                else:
                    self.assertTrue(noabs_filter.accept(clazz), "Path %s is not abstract!" % fullpath)
                num_files += 1

        print "Filtered %s files" % num_files

class TestPackager(unittest.TestCase):

    @classmethod
    def setUpClass(self):
        self.output_dir = tempfile.mkdtemp()
        self.cache_dir = tempfile.mkdtemp()
        self.project = mavenproject.MavenProject(TEST_PROJECT_PATH)
        self.packager = packager.Packager(self.project, self.output_dir, cache_dir=self.cache_dir)

    def print_output_dir(self):
        for root, dirs, files in os.walk(self.output_dir):
            print "Contents of", root
            for f in files:
                print os.path.join(root, f)
            print

    @classmethod
    def tearDownClass(self):
        #self.print_output_dir()
        shutil.rmtree(self.output_dir)
        shutil.rmtree(self.cache_dir)

    def test_package_target_dirs(self):
        self.packager._package_target_dirs()

    def test_package_maven_dependencies(self):
        self.packager._package_maven_dependencies()
        # Package from the cache dir
        cpack = packager.Packager(self.project, tempfile.mkdtemp(), cache_dir=self.cache_dir)
        cpack._package_maven_dependencies()

    def test_manifest(self):
        # Build a manifest and write it out
        built_manifest = packager.Manifest.build_from_project(os.path.dirname(__file__))
        path = os.path.join(self.output_dir, "manifest")
        built_manifest.write(path)
        # Read it back in and make sure it's equal
        read_manifest = packager.Manifest.read(path)
        self.assertEqual(built_manifest, read_manifest)
        # Mess up the manifest and make sure it's not equal
        read_manifest.git_branch = "not/a/branch"
        read_manifest.write(path)
        read_manifest = packager.Manifest.read(path)
        self.assertNotEqual(built_manifest, read_manifest)

class TestIsolate(unittest.TestCase):

    @classmethod
    def setUp(self):
        self.output_dir = tempfile.mkdtemp()

    @classmethod
    def tearDown(self):
        #shutil.rmtree(self.output_dir)
        pass

    def test_isolate(self):
        # Write a file specifying the extra dependencies
        patterns = ["*.properties"]
        deps = {
                "file_patterns": patterns
        }
        dep_file = os.path.join(self.output_dir, "deps")
        with open(dep_file, "w") as o:
            json.dump(deps, o)
        i = isolate.Isolate(TEST_PROJECT_PATH, self.output_dir,
                            extra_deps_file=dep_file)
        i.package()
        i.generate()
        num_files = 0
        for root, dirs, files in os.walk(self.output_dir):
            for f in files:
                for pattern in patterns:
                    if fnmatch.fnmatch(f, pattern) and "target" in root:
                        num_files += 1
                        break
        # Expect one property file per target directory (3 submodules, 1 root)
        self.assertEqual(4, num_files)

if __name__ == "__main__":
    unittest.main()
