import os
import shutil
import tempfile
import unittest

import enumerators

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
        for root, dirs, files in os.walk("/home/andrew/dev/hadoop/trunk"):
            for f in files:
                fullpath = os.path.realpath(os.path.join(root, f))
                if f.endswith(".class"):
                    print "Path: ",fullpath
                    num_files += 1
                    if f.startswith("Abstract"):
                        self.assertFalse(noabs_filter.accept(fullpath))
                    else:
                        self.assertTrue(noabs_filter.accept(fullpath))
        print "Filtered %s files" % num_files

if __name__ == "__main__":
    unittest.main()
