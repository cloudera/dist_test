import os
import shutil
import tempfile
import unittest

from .. import mavenproject, packager, isolate, classfile

TEST_RESOURCES = os.path.join(os.path.abspath(os.path.dirname(__file__)), "test-resources")

TEST_PROJECT_PATH = "/home/andrew/dev/hadoop/cdh5-2.6.0_dev"

class TestMavenProject(unittest.TestCase):

    def test_MavenProject(self):
        project = mavenproject.MavenProject(TEST_PROJECT_PATH)
        for module in project.modules:
            if "hadoop-kms" in module.root:
                print module.root
                for c in module.test_classes:
                    print c.name
                self.assertEquals(1, len(module.test_artifacts))
                self.assertTrue("test-sources.jar" in module.test_artifacts[0])

class TestFilters(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.temp)

    def test_NoAbstractClassFilter(self):
        noabs_filter = mavenproject.NoAbstractClassFilter()
        # Test some abstract and concrete classes
        num_files = 0
        for root, dirs, files in os.walk(TEST_RESOURCES, "classes/"):
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
