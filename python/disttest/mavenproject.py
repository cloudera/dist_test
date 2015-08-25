import os
import logging

import classfile

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class Module:

    def __init__(self, root):
        self.root = root
        self.pom = os.path.join(root, "pom.xml")
        self.test_classes = []
        self.source_artifacts = []
        self.test_artifacts = []

class MavenProject:

    def __init__(self, project_root):
        if not os.path.isdir(project_root):
            raise Exception("Path " + project_root + "is not a directory!")
        if not project_root.endswith("/"):
            project_root += "/"
        self.project_root = project_root
        self.modules = []
        self.__filters = [PotentialTestClassNameFilter(), NoAbstractClassFilter()]
        self._walk()

    def _walk(self):
        # Find the modules first, directories that have a pom.xml and a target dir
        for root, dirs, files in os.walk(self.project_root):
            if "pom.xml" in files and "target" in dirs:
                self.modules.append(Module(root))

        # For each module, look for test classes within target dir
        for module in self.modules:
            logger.debug("Traversing module %s", module.root)
            for root, dirs, files in os.walk(os.path.join(module.root, "target")):
                abs_files = [os.path.join(root, f) for f in files]
                # Make classfile objects for everything that's a valid class
                classfiles = self.__build_classfiles(abs_files)
                # Apply classfile filters
                for fil in self.__filters:
                    classfiles = [c for c in classfiles if fil.accept(c)]
                # Set module's classes to the filtered classfiles
                module.test_classes += classfiles

        # For each module, look for test-sources jars
        # These will later be extracted
        for module in self.modules:
            target_root = os.path.join(module.root, "target")
            for entry in os.listdir(target_root):
                abs_path = os.path.join(target_root, entry)
                if os.path.isfile(abs_path):
                    if entry.endswith("-test-sources.jar") or entry.endswith("-tests.jar"):
                        module.test_artifacts.append(abs_path)
                    elif entry.endswith(".jar") and not entry.endswith("-sources.jar") and not entry.endswith("-javadoc.jar"):
                        module.source_artifacts.append(abs_path)

        num_modules = len(self.modules)
        num_classes = reduce(lambda x,y: x+y,\
                             [len(m.test_classes) for m in self.modules])
        logging.info("Found %s modules with %s test classes in %s",\
                     num_modules, num_classes, self.project_root)

    @staticmethod
    def __build_classfiles(files):
        classfiles = []
        for f in files:
            # Must be a file
            if not os.path.isfile(f):
                continue
            name = os.path.basename(f)
            # Only class files
            if not name.endswith(".class"):
                continue
            clazz = classfile.Classfile(f)
            classfiles.append(clazz)
        return classfiles


class ClassfileFilter:
    @staticmethod
    def accept(clazz):
        return True


class PotentialTestClassNameFilter(ClassfileFilter):
    @staticmethod
    def accept(clazz):
        f = os.path.basename(clazz.classfile)
        # No nested classes
        if "$" in f:
            return False
        # Must end in ".class". This is checked earlier, but be paranoid.
        if not f.endswith(".class"):
            return False
        # Match against default Surefire pattern
        name = f[:-len(".class")]
        if not name.startswith("Test") and \
        not name.endswith("Test") and \
        not name.endswith("TestCase"):
            return False
        return True


class NoAbstractClassFilter(ClassfileFilter):
    @staticmethod
    def accept(clazz):
        return not (clazz.is_interface() or clazz.is_abstract())
