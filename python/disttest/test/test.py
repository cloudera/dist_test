import os
import shutil
import tempfile
import unittest

from .. import mavenproject, packager, isolate

TEST_RESOURCES = os.path.join(os.path.abspath(os.path.dirname(__file__)), "test-resources")

TEST_PROJECT_PATH = "/home/andrew/dev/hadoop/cdh5-2.6.0_5.4.0"

class TestMavenProject(unittest.TestCase):

    def test_MavenProject(self):
        project = mavenproject.MavenProject(TEST_PROJECT_PATH)
        for module, classes in project.get_modules_to_classes().iteritems():
            if "hadoop-kms" in module:
                print module
                for c in classes:
                    print c

class TestFilters(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.mkdtemp()
        open(os.path.join(self.temp, "foofile"), "w").close()

    def tearDown(self):
        shutil.rmtree(self.temp)

    def test_AnyFileFilter(self):
        any_filter = mavenproject.AnyFileFilter()
        self.assertFalse(any_filter.accept(os.path.join(self.temp, "nosuchfileexists")))
        self.assertTrue(any_filter.accept(os.path.join(self.temp, "foofile")))

    def test_NoAbstractClassFilter(self):
        noabs_filter = mavenproject.NoAbstractClassFilter()
        num_files = 0
        for root, dirs, files in os.walk(TEST_RESOURCES, "classes/"):
            for f in files:
                fullpath = os.path.realpath(os.path.join(root, f))
                if root.endswith("abstract"):
                    self.assertFalse(noabs_filter.accept(fullpath), "Path %s is abstract!" % fullpath)
                else:
                    self.assertTrue(noabs_filter.accept(fullpath), "Path %s is not abstract!" % fullpath)
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
