#!/usr/bin/python

import os
import struct
import logging

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.DEBUG)

class Classfile:
    """
Parser for Java classfile headers.
See reference material at:
    https://docs.oracle.com/javase/specs/jvms/se7/html/jvms-4.html

Currently only supports the access_flags field.
"""

    def __init__(self, classfile):
        self.classfile = classfile
        with open(classfile, "rb") as f:
            self.__parse(f)

    def __skip_constant(self, f):
        constant_tag = {
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
        constant_sizes = {
            "Class": 3,
            "Fieldref": 5,
            "Methodref": 5,
            "InterfaceMethodref": 5,
            "String": 3,
            "Integer": 5,
            "Float": 5,
            "Long": 9,
            "Double": 9,
            "NameAndType": 5,
            "MethodHandle": 4,
            "MethodType": 3,
            "InvokeDynamic": 5,
        }

        """Read a single constant pool entry from a stream."""
        tag = ord(f.read(1))
        logger.debug("Tag is %s", str(tag))
        name = constant_tag[tag]
        # Handle Utf8 special since it's variable sized
        if name == "Utf8":
            length = struct.unpack(">H", f.read(2))[0]
            f.read(length)
        else:
            f.read(constant_sizes[name])

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
        logger.debug("Magic constant is %s" % self.__magic)
        assert self.__magic == 0xCAFEBABE

        major, minor = struct.unpack(">HH", f.read(4)) # minor, major
        logger.debug("Minor, major is %s, %s", minor, major)

        cp_count = struct.unpack(">H", f.read(2))[0]
        logger.debug("%s constants in constant pool", cp_count)
        for c in xrange(cp_count-1):
            self.__skip_constant(f)

        self.__access_flags = unpack(">H", f.read(2))[0]

    def is_interface(self):
        return self.__access_flags & 0x0200 > 0

    def is_abstract(self):
        return self.__access_flags & 0x0400 > 0
