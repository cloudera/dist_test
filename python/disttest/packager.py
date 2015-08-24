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
        self.__project_root = maven_project.project_root
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

    def __copy(self, module_path, input_path):
        # module_path is absolute, e.g. /dev/parent-module/sub-module
        # input_path is absolute, e.g. /dev/parent-module/sub-module/target/foo
        assert input_path.startswith(module_path)

        # Form up the output path
        # Get the relpath of the input, join to the output folder
        input_relpath = os.path.relpath(input_path, self.__project_root)
        output_path = os.path.join(self.__output_root, input_relpath)

        # Create the parent directory in the output root if it doesn't exist
        parent_output_path = os.path.dirname(output_path)
        self.__mkdirs_recursive(parent_output_path)

        # Copy both files and directories (recursively)
        if os.path.isfile(input_path):
            shutil.copyfile(input_path, output_path)
        elif os.path.isdir(input_path):
            # Do the copy with ignore patterns
            shutil.copytree(input_path, output_path, ignore=shutil.ignore_patterns(*self.__ignore))
        else:
            raise Exception("Cannot copy something that's not a file or directory: " + input_path)

    def package_target_dirs(self):
        # Create the same target directory folder structure under the output directory
        for module in self.__maven_project.modules:
            for artifact in module.test_artifacts:
                self.__copy(module.root, artifact)

        logger.info("Packaged %s modules to output directory %s",\
                    len(self.__maven_project.modules), self.__output_root)

    def package_maven_dependencies(self):
        """Put dependencies from the maven repo into __MAVEN_REL_ROOT in the output directory"""

        # Use Maven to copy dependencies into output dir
        cmd = "mvn -q dependency:copy-dependencies -Dmdep.useRepositoryLayout=true -Dmdep.copyPom -DoutputDirectory=%s"
        output_path = os.path.join(self.__output_root, self.__MAVEN_REL_ROOT)
        cmd = cmd % output_path
        echo "Invoking maven via `%s`" % cmd
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
