#!/usr/bin/python

import os
import struct
import logging

logger = logging.getLogger(__name__)
#logging.basicConfig(level=logging.DEBUG)

class Classfile:
    """
Models a Java classfile. Determines two important pieces of information:
    * The package name (based on the directory structure)
    * If the class is abstract or an interface (by parsing the classfile header)

See directory structure documentation at:
    https://docs.oracle.com/javase/tutorial/java/package/managingfiles.html

See classfile format reference material at:
    https://docs.oracle.com/javase/specs/jvms/se7/html/jvms-4.html
    """

    def __init__(self, classfile):
        self.classfile = classfile
        if not classfile.endswith(".class"):
            raise Exception("File %s is not a java classfile" % classfile)
        # Determine the name-with-package from the folder layout
        self.name = Classfile.__determine_qualified_name(self.classfile)
        # Parse the classfile
        with open(classfile, "rb") as f:
            self.__parse(f)

    @staticmethod
    def __determine_qualified_name(path):
        # We're looking for a folder named "classes" or "test-classes"
        # See: https://docs.oracle.com/javase/tutorial/java/package/managingfiles.html
        components = Classfile.__splitall(path)[:-1]
        package = None
        for x in xrange(len(components)):
            if components[x] in ("classes", "test-classes"):
                package = ".".join(components[x+1:])
                break
        if package is None:
            raise Exception("Could not determine package name of file " + path)
        # Trim off ".class" from the basename to get name of class
        filename = os.path.basename(path)
        assert filename.endswith(".class")
        classname = filename[:-len(".class")]
        # Join together. Handles when there is an empty package.
        return ".".join([package, classname])

    @staticmethod
    def __splitall(path):
        components = []
        while True:
            head, tail = os.path.split(path)
            if head is path: # happens for /, since its parent is still /
                components.append(head)
                break
            elif tail is path: # relative paths, terminates with path as tail
                components.append(tail)
                break
            else:
                path = head
                components.append(tail)
        # Return reversed result since we appended back to front
        return [x for x in reversed(components)]

    __constant_tag = {
        7: "Class",
        9: "Fieldref",
        10: "Methodref",
        11: "InterfaceMethodref",
        8: "String",
        3: "Integer",
        4: "Float",
        5: "Long",
        6: "Double",
        12: "NameAndType",
        1: "Utf8",
        15: "MethodHandle",
        16: "MethodType",
        18: "InvokeDynamic",
    }

    # This does not include Utf8 since it's variable sized
    # Does not count the first byte used for the tag field
    __constant_sizes = {
        "Class": 2,
        "Fieldref": 4,
        "Methodref": 4,
        "InterfaceMethodref": 4,
        "String": 2,
        "Integer": 4,
        "Float": 4,
        "Long": 8,
        "Double": 8,
        "NameAndType": 4,
        "MethodHandle": 3,
        "MethodType": 2,
        "InvokeDynamic": 4,
    }

    def __skip_constants(self, f):
        """Skip over constant pool count and entries from a stream."""

        # The count is 1-indexed, so need to subtract 1 everywhere
        self.__cp_count = struct.unpack(">H", f.read(2))[0]
        logger.debug("%s constants in constant pool", self.__cp_count)

        idx = 0
        while idx < self.__cp_count - 1:
            logger.debug("Skipping constant %s of %s", idx, self.__cp_count - 1)
            tag = ord(f.read(1))
            name = self.__constant_tag[tag]
            logger.debug("Tag is %s", name)
            # Handle Utf8 special since it's variable sized
            if name == "Utf8":
                length = struct.unpack(">H", f.read(2))[0]
                logger.debug("Reading string of len %s", length)
                f.read(length)
            else:
                f.read(self.__constant_sizes[name])

            idx += 1
            # Long and Double take up two entries, advance cp count again.
            # See: https://docs.oracle.com/javase/specs/jvms/se7/html/jvms-4.html#jvms-4.4.5
            if name in ("Long", "Double"):
                idx += 1

    def __parse(self, f):
        """Parse header of provided classfile, setting member variables."""
        # Header file format:
        # u4             magic;
        # u2             minor_version;
        # u2             major_version;
        # u2             constant_pool_count;
        # cp_info        constant_pool[constant_pool_count-1];
        # u2             access_flags;
        # ...
        self.__magic = struct.unpack(">I", f.read(4))[0]
        logger.debug("Magic constant is %s" % hex(self.__magic))
        assert self.__magic == 0xCAFEBABE

        self.__minor, self.__major = struct.unpack(">HH", f.read(4))
        logger.debug("Minor, major is %s, %s", self.__minor, self.__major)

        self.__skip_constants(f)

        self.__access_flags = struct.unpack(">H", f.read(2))[0]

    def access_flags(self):
        return self.__access_flags

    def is_interface(self):
        return self.__access_flags & 0x0200 > 0

    def is_abstract(self):
        return self.__access_flags & 0x0400 > 0
