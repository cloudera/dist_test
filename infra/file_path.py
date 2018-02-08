#!/usr/bin/env python

import logging
import tempfile
import os
import stat
import sys

def set_read_only(path, read_only):
  """Sets or resets the write bit on a file or directory.

  Zaps out access to 'group' and 'others'.
  """
  assert isinstance(read_only, bool), read_only
  mode = os.lstat(path).st_mode
  # TODO(maruel): Stop removing GO bits.
  if read_only:
    mode = mode & 0500
  else:
    mode = mode | 0200
  if hasattr(os, 'lchmod'):
    os.lchmod(path, mode)  # pylint: disable=E1101
  else:
    if stat.S_ISLNK(mode):
      # Skip symlink without lchmod() support.
      logging.debug(
          'Can\'t change %sw bit on symlink %s',
          '-' if read_only else '+', path)
      return

    # TODO(maruel): Implement proper DACL modification on Windows.
    os.chmod(path, mode)

def make_tree_writeable(root):
  """Makes all the files in the directories writeable.

  Also makes the directories writeable, only if it makes sense on the platform.

  It is different from make_tree_deleteable() because it unconditionally affects
  the files.
  """
  logging.debug('make_tree_writeable(%s)', root)
  assert os.path.isabs(root), root
  if sys.platform != 'win32':
    set_read_only(root, False)
  for dirpath, dirnames, filenames in os.walk(root, topdown=True):
    for filename in filenames:
      set_read_only(os.path.join(dirpath, filename), False)
    if sys.platform != 'win32':
      # It must not be done on Windows.
      for dirname in dirnames:
        set_read_only(os.path.join(dirpath, dirname), False)

def ensure_command_has_abs_path(command, cwd):
  """Ensures that an isolate command uses absolute path.

  This is needed since isolate can specify a command relative to 'cwd' and
  subprocess.call doesn't consider 'cwd' when searching for executable.
  """
  if not os.path.isabs(command[0]):
    command[0] = os.path.abspath(os.path.join(cwd, command[0]))

def is_same_filesystem(path1, path2):
  """Returns True if both paths are on the same filesystem.

  This is required to enable the use of hardlinks.
  """
  assert os.path.isabs(path1), path1
  assert os.path.isabs(path2), path2
  return os.stat(path1).st_dev == os.stat(path2).st_dev


def make_temp_dir(prefix, root_dir):
  """Returns a temporary directory on the same file system as root_dir."""
  base_temp_dir = None
  if (root_dir and not is_same_filesystem(root_dir, tempfile.gettempdir())):
    base_temp_dir = os.path.dirname(root_dir)
  return tempfile.mkdtemp(prefix=prefix, dir=base_temp_dir)

