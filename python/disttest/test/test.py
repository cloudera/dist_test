import os
import shutil
import tempfile
import unittest

from .. import enumerators

TEST_RESOURCES = os.path.join(os.path.abspath(os.path.dirname(__file__)), "test-resources")

class TestEnumerators(unittest.TestCase):

    def test_pattern_enumerator(self):
        enum = enumerators.PatternEnumerator("/home/andrew/dev/hadoop/trunk/hadoop-common-project/hadoop-kms")
        for module, classes in enum.get_modules_to_classes().iteritems():
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
        any_filter = enumerators.AnyFileFilter()
        self.assertFalse(any_filter.accept(os.path.join(self.temp, "nosuchfileexists")))
        self.assertTrue(any_filter.accept(os.path.join(self.temp, "foofile")))

    def test_NoAbstractClassFilter(self):
        noabs_filter = enumerators.NoAbstractClassFilter()
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

if __name__ == "__main__":
    unittest.main()
