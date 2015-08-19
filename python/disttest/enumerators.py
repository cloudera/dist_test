#!/usr/bin/python

import os
import logging

import classfile

class Enumerator:
    def __init__(self, directory):
        self.directory = directory
        self.modules_to_classes = {}

    def get_modules(self):
        return self.modules_to_classes.keys()

    def get_modules_to_classes(self):
        return self.modules_to_classes

class PatternEnumerator(Enumerator):

    def __init__(self, directory):
        Enumerator.__init__(self, directory)
        #self.filters = [AnyFileFilter(), PotentialTestClassNameFilter(), NoAbstractClassFilter()]
        self.filters = [AnyFileFilter(), PotentialTestClassNameFilter()]
        self._walk()

    def add_filter(self, f):
        return self.modules_to_classes.keys()

    def get_modules_to_classes(self):
        return self.modules_to_classes

class PatternEnumerator(Enumerator):

    def __init__(self, directory):
        Enumerator.__init__(self, directory)
        #self.filters = [AnyFileFilter(), PotentialTestClassNameFilter(), NoAbstractClassFilter()]
        self.filters = [AnyFileFilter(), PotentialTestClassNameFilter()]
        self._walk()

    def add_filter(self, f):
        self.filters += [f]

    def _walk(self):
        # Find the modules first, directories that have a pom.xml and a target dir
        for root, dirs, files in os.walk(self.directory):
            if "pom.xml" in files and "target" in dirs:
                self.modules_to_classes[root] = []
        # For each module, look for test classes within target dir
        for module in self.modules_to_classes.keys():
            module_dir = os.path.join(module, "target")
            print "Traversing module", module_dir
            for root, dirs, files in os.walk(os.path.join(module, "target")):
                # Apply all the filters
                filtered = [os.path.join(root, f) for f in files]
                for fil in self.filters:
                    filtered = [x for x in filtered if fil.accept(x)]
                # Add filtered files to dict
                for f in filtered:
                    self.modules_to_classes[module].append(os.path.join(root, f))

class FileFilter:
    def accept(self, f):
        pass

class AnyFileFilter(FileFilter):
    def accept(self, f):
        return os.path.isfile(f)

class PotentialTestClassNameFilter(FileFilter):
    def accept(self, f):
        f = os.path.basename(f)
        # Only class files
        if not f.endswith(".class"):
            return False
        # No nested classes
        if "$" in f:
            return False
        # Match against default Surefire pattern
        name = f[:-len(".class")]
        if not name.startswith("Test") and \
           not name.endswith("Test") and \
           not name.endswith("TestCase"):
            return False
        return True

class NoAbstractClassFilter(FileFilter):
    def accept(self, f):
        clazz = classfile.Classfile(f)
        return not (clazz.is_interface() or clazz.is_abstract())

