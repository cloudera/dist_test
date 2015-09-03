import os
import shutil
import shlex, subprocess
import tempfile
import unittest

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
                ["TestLinkedListReversal", "TestHelloWorld", "AppTest"]),
            ((["Test*"], None),
                ["TestLinkedListReversal", "TestHelloWorld"]),
            ((["*Linked*"], None),
                ["TestLinkedListReversal"]),
            ((["*Test"], None),
                ["AppTest"]),
            ((None, ["Test*"]),
                ["AppTest"]),
            ((None, ["AppTest"]),
                ["TestLinkedListReversal", "TestHelloWorld"]),
            ((None, ["*"]),
                []),
            ((["Test*"], ["*Reversal"]),
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
        self.project = mavenproject.MavenProject(TEST_PROJECT_PATH)
        self.packager = packager.Packager(self.project, self.output_dir)

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
        pass

    def test_package_target_dirs(self):
        self.packager.package_target_dirs()

    def test_package_maven_dependencies(self):
        self.packager.package_maven_dependencies()

class TestIsolate(unittest.TestCase):

    @classmethod
    def setUp(self):
        self.output_dir = tempfile.mkdtemp()

    @classmethod
    def tearDown(self):
        #shutil.rmtree(self.output_dir)
        pass

    def test_isolate(self):
        i = isolate.Isolate(TEST_PROJECT_PATH, self.output_dir)
        i.package()
        i.generate()

if __name__ == "__main__":
    unittest.main()
