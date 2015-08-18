import os
import shutil
import tempfile
import unittest

from .. import enumerators

class TestEnumerators(unittest.TestCase):

    def test_pattern_enumerator(self):
        enumerator = enumerators.PatternEnumerator("/tmp")

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

    def test_NoAbstractFilter(self):
        noabs_filter = enumerators.NoAbstractFilter()
        num_files = 0
        for root, dirs, files in os.walk(os.path.dirname(__file__), "/test-resources/classes/"):
            for f in files:
                fullpath = os.path.realpath(os.path.join(root, f))
                if f.endswith(".class") and "/test-classes/" in fullpath and not "$" in fullpath:
                    if "/abstract/" in fullpath:
                        self.assertFalse(noabs_filter.accept(fullpath))
                    elif "/concrete/" in fullpath:
                        self.assertTrue(noabs_filter.accept(fullpath))
                    num_files += 1

        print "Filtered %s files" % num_files

if __name__ == "__main__":
    unittest.main()
