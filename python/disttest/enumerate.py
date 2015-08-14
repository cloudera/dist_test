#!/usr/bin/python

import os

class Enumerator:
    def __init__(self, directory):
        self.directory = directory
        self.modules_to_classes = {}
        self.__walk()
        self.__filter()

    def __walk(self):
        pass

    def __filter():
        pass

    def get_modules(self):
        return self.modules_to_classes.keys()

    def get_modules_to_classes(self):
        return self.modules_to_classes

def PatternEnumerator(Enumerator):

    def __init__(self, directory):
        Enumerator.__init__(directory)

    def __walk(self):
        # Find the modules first, directories that have a pom.xml and a target dir
        for root, files, dirs in os.walk(directory):
            if files.contains("pom.xml") and dirs.contains("target"):
                self.modules_to_classes[root] = []
        # For each module, look for test classes within target dir
        for module in self.modules_to_classes.keys():
            for root, files, dirs in os.walk(os.path.join(module, "target")):
                for f in files:
                    # Only class files
                    if not f.endswith(".class"):
                        continue
                    # No nested classes
                    if f.contains("$"):
                        continue
                    # Match against default Surefire pattern
                    name = f[:-len(".class")]
                    if not name.startswith("Test") and \
                       not name.endswith("Test") and \
                       not name.endswith("TestCase"):
                        continue
                    modules_to_classes[module].append(os.path.join(root, f))

    def __filter(self):
        for k, v in modules_to_classes.iteritems():
            v = [x for x in v if NoAbstractFilter.accept(v)]

class FileFilter:
    def accept(self, classfile):
        pass

class AnyFileFilter(FileFilter):
    def accept(self, classfile):
        return True

class NoAbstractFilter(FileFilter):
    def accept(self, classfile):
        clazz = JavaClassfile(classfile)
        return !(clazz.is_interface() or clazz.is_abstract())

