import os
import logging
import fnmatch
import sys
import re

import classfile

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class Module:
    """Struct-like class for holding information about a Maven module.

    disttest Modules have a notion of hierarchy via the root_module and submodules.
    These are only a loose approximation of an actual Maven multi-module project,
    since the hierarchy is based on the folder structure rather than parent poms."""

    def __init__(self, root):
        self.root = root
        self.root_module = None
        self.pom = os.path.join(root, "pom.xml")
        self.test_classes = []
        self.source_artifacts = []
        self.test_artifacts = []
        self.name = os.path.basename(self.root)
        self.submodules = []

class NotMavenProjectException(Exception):
    pass

class ModuleNotFoundException(Exception):
    pass

class MavenProject:
    """Represents the contents of a Maven project.

    On initialization, a MavenProject walks the provided path looking for Maven
    modules, artifacts, and test classes.

    Test case enumeration is not guaranteed to match with Surefire.
    MavenProject uses the default Surefire include pattern to detect files
    look like test cases (e.g. TestFoo), and parses the classfile to do some
    basic verification. Inconsistencies arise when there are custom Surefire
    include and exclude patterns in the pom, or if a class does not actually
    have any tests in it.

    MavenProject also looks for built jars within the target folders of each module.
    These are used later when packaging the dependencies to run unit tests.
    """

    def __init__(self, project_root, include_modules=None, exclude_modules=None, include_patterns=None, exclude_patterns=None):
        # Normalize the path
        if not project_root.endswith("/"):
            project_root += "/"
        # Validate some basic expectations
        if not os.path.isdir(project_root):
            raise NotMavenProjectException("Path " + project_root + "is not a directory!")
        if not os.path.isfile(os.path.join(project_root, "pom.xml")):
            raise NotMavenProjectException("No pom.xml file found in %s, is this a Maven project?" % project_root)
        self.project_root = project_root
        self.modules = [] # All modules in the project
        self.included_modules = set() # Modules that match the include_modules filter
        self.excluded_modules = exclude_modules
        self.__include_modules = include_modules
        # Default filters to find test classes
        self.__filters = [PotentialTestClassNameFilter(), NoAbstractClassFilter()]
        # Additional user-specified include and exclude patterns
        # Prepend because these are likely more selective than the default filters
        if include_patterns is not None:
            include_filter = IncludePatternsFilter(include_patterns)
            self.__filters.insert(0, include_filter)
        if exclude_patterns is not None:
            exclude_filter = ExcludePatternsFilter(exclude_patterns)
            self.__filters.insert(0, exclude_filter)
        self._walk()


    def _construct_parent_child_relationships(self):
        """Construct the parent->child relationship for submodules based on
        the directory hierarchy. Note that this is different from the Maven
        notion of parent poms, which are specified in the pom.xml."""
        # Sort the modules based on path length, this guarantees we find parents before children
        path_to_module = {}
        for module in self.modules:
            path_to_module[module.root] = module
        assert len(path_to_module) > 0
        sorted_mod_paths = sorted(path_to_module.keys())
        # Trim off the first, it's the root
        self.root_module = path_to_module[sorted_mod_paths[0]]
        sorted_mod_paths = sorted_mod_paths[1:]
        for mod_path in sorted_mod_paths:
            # Chop path components off the tail until we find a matching parent module
            found = False
            parent_path = mod_path
            while not found:
                parent_path = os.path.dirname(parent_path)
                if parent_path == "/":
                    break
                if parent_path in path_to_module.keys():
                    found = True
                    break
            if not found:
                raise Exception("Could not find a parent of Maven submodule at %s, have you run mvn package?" % mod_path)
            # Append self to parent's list of children
            parent_module = path_to_module[parent_path]
            parent_module.submodules.append(path_to_module[mod_path])

    def _filter_excluded_modules(self):
        if self.excluded_modules is not None:
            excluded = [m for m in self.included_modules if m.name in self.excluded_modules]
            for m in excluded:
                self._exclude_module_tree(m)

    def _exclude_module_tree(self, module):
        self.included_modules.remove(module)
        for submodule in module.submodules:
            self._exclude_module_tree(submodule)

    def _filter_included_modules(self):
        """Determine which of the modules are included (if specified)"""
        # If no modules were specified, they're all included
        if self.__include_modules is None:
            self.included_modules = set(self.modules)
            return

        # If include_modules was specified, filter the found module list and check for missing modules
        # Filter to just the specified modules
        included = [m for m in self.modules if m.name in self.__include_modules]
        # Mismatch in length means we're missing some
        if len(included) != len(self.__include_modules):
            for m in included:
                self.__include_modules.remove(m.name)
            assert len(self.__include_modules) > 0
            raise ModuleNotFoundException("Could not find specified modules: " + " ".join(self.__include_modules))
        # Add modules to member set, including submodules
        for m in included:
            self._include_module_tree(m)

    def _include_module_tree(self, module):
        self.included_modules.add(module)
        for submodule in module.submodules:
            self._include_module_tree(submodule)

    def _find_all_modules(self):
        # Modules are directories that have a pom.xml and a target dir
        for root, dirs, files in os.walk(self.project_root):
            if "pom.xml" in files:
                self.modules.append(Module(os.path.normpath(root)))

    def _walk(self):
        """Walk the project directory to enumerate the modules, test classes,
        and project artifacts within a MavenProject."""

        # Find the modules first, directories that have a pom.xml and a target dir
        self._find_all_modules()

        if len(self.modules) == 0:
            logger.error("No modules with target directories found. Did you forget to build the project?")
            sys.exit(1)

        self._construct_parent_child_relationships()

        self._filter_included_modules()
        self._filter_excluded_modules()

        # For each included module, look for test classes within target dir
        for module in self.included_modules:
            logger.debug("Traversing module %s", module.root)
            for root, dirs, files in os.walk(os.path.join(module.root, "target")):
                abs_files = [os.path.join(root, f) for f in files]
                # Make classfile objects for everything that's a valid class
                classfiles = self.__get_classfiles(abs_files)
                # Apply classfile filters
                for fil in self.__filters:
                    classfiles = [c for c in classfiles if fil.accept(c)]
                # Set module's classes to the filtered classfiles
                module.test_classes += classfiles

        # For each module, look for test-sources jars
        # These will later be extracted
        for module in self.modules:
            target_root = os.path.join(module.root, "target")
            if not os.path.exists(target_root):
                continue
            for entry in os.listdir(target_root):
                abs_path = os.path.join(target_root, entry)
                if os.path.isfile(abs_path):
                    if entry.endswith("-test-sources.jar") or entry.endswith("-tests.jar"):
                        # Do not need test jars from a module if we're not running its tests
                        if module in self.included_modules:
                            module.test_artifacts.append(abs_path)
                    elif entry.endswith(".jar") and not entry.endswith("-sources.jar") and not entry.endswith("-javadoc.jar"):
                        module.source_artifacts.append(abs_path)

        num_classes = reduce(lambda x,y: x+y,\
                             [0] + [len(m.test_classes) for m in self.included_modules])
        logging.info("Found %s included modules out of %s total modules with %s test classes within project %s",\
                     len(self.included_modules), len(self.modules), num_classes, self.project_root)

    @staticmethod
    def __get_classfiles(files):
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

class IncludePatternsFilter(ClassfileFilter):
    def __init__(self, patterns = None):
        self.patterns = []
        self.__reobjs = []
        if patterns is not None:
            self.patterns = patterns
            regexes = [fnmatch.translate(p) for p in patterns]
            self.__reobjs = [re.compile(r) for r in regexes]

    def accept(self, clazz):
        matched = False
        for reobj in self.__reobjs:
            if reobj.match(clazz.classname) is not None:
                matched = True
                break
        return matched

class ExcludePatternsFilter(IncludePatternsFilter):
    def accept(self, clazz):
        """Exclude is the opposite of the include filter."""
        return not IncludePatternsFilter.accept(self, clazz)
