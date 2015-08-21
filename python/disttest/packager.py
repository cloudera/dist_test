import errno
import os
import logging
import shlex, subprocess
import shutil

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class Packager:

    # Call it this for familiarity
    __MAVEN_REL_ROOT = ".m2/repository"

    def __init__(self, maven_project, output_root, ignore=None):
        self.__maven_project = maven_project
        self.__input_root = maven_project.project_root
        self.__output_root = output_root
        if ignore is None:
            self.__ignore = ["*.jar", "*.war", "surefire-reports"]
        else:
            self.__ignore = ignore

    def __mkdirs_recursive(self, path):
        try:
            os.makedirs(path)
            logger.debug("Created directory %s", path)
        except OSError as exc:
            if exc.errno == errno.EEXIST and os.path.isdir(path):
                pass
            else:
                raise

    def __copy(self, module, tree):
        # These are absolute paths, trim to get just the relative path
        relpath = os.path.relpath(module, self.__input_root)
        # Create the parent directory if it doesn't exist
        parent_relpath = os.path.relpath(module, os.path.dirname(self.__input_root))
        parent_output_path = os.path.join(self.__output_root, parent_relpath)
        self.__mkdirs_recursive(parent_output_path)
        # Form up the input and output paths
        input_path = os.path.join(module, tree)
        output_path = os.path.join(self.__output_root, relpath, tree)
        # Do the copy with ignore patterns
        if os.path.isfile(input_path):
            shutil.copyfile(input_path, output_path)
        elif os.path.isdir(input_path):
            shutil.copytree(input_path, output_path, ignore=shutil.ignore_patterns(*self.__ignore))
        else:
            raise Exception("Cannot copy something that's not a file or directory: " + input_path)

    def package_target_dirs(self):
        # Create the same target directory folder structure under the output directory
        for module in self.__maven_project.get_modules():
            self.__copy(module, "pom.xml")
            self.__copy(module, "target")

        logger.info("Packaged %s target directories to output directory %s",\
                    len(self.__maven_project.get_modules()), self.__output_root)

    def package_maven_dependencies(self):
        """Put dependencies from the maven repo into __MAVEN_REL_ROOT in the output directory"""

        # Use Maven to copy dependencies into output dir
        cmd = "mvn dependency:copy-dependencies -Dmdep.useRepositoryLayout=true -Dmdep.copyPom -DoutputDirectory=%s"
        output_path = os.path.join(self.__output_root, self.__MAVEN_REL_ROOT)
        cmd = cmd % output_path
        args = shlex.split(cmd)
        p = subprocess.Popen(args, cwd=self.__maven_project.project_root)
        p.wait()

        logger.info("Finished copying maven dependencies to %s", output_path)

    def get_relative_output_paths(self):
        """Generate relative paths of files in the output directory."""
        paths = []
        for root, dirs, files in os.walk(self.__output_root):
            root_relpath = os.path.relpath(root, self.__output_root)
            for f in files:
                paths += [os.path.join(root_relpath, f)]
        return paths
