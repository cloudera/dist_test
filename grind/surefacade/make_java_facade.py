#!/usr/bin/env python2.7

import tempfile
import os

java_home = os.environ["JAVA_HOME"]

if java_home is None or len(java_home) == 0:
  print "JAVA_HOME is not set!"
  sys.exit(1)

out_dir = tempfile.mkdtemp()

wrapper_java = """#!/usr/bin/env bash

echo "$@" >> /tmp/java.log

if [[ "$@" == *surefirebooter* ]]; then
  for arg in "$@" ; do
    if [ -e "$arg" ]; then
      ln $arg /tmp/
    fi
  done
  echo "Z000," # Custom ASCII protocol for surefire
  exit 0
fi

# Need to call the real java here, something like:
# exec /home/todd/sw/jdk1.8.0_45/jre/bin/java "$@"
%s
""" % (os.path.join(java_home, "jre", "bin", "java") + ' "$@"')

for root, dirs, files in os.walk(java_home):
  relroot = os.path.relpath(root, java_home)
  for f in files:
    out_path = os.path.join(out_dir, relroot, f)
    # If it looks like a java binary, substitute our java wrapper instead
    if os.path.basename(root) == "bin" and f == "java":
      with open(out_path, "wt") as o:
        o.write(wrapper_java)
      os.chmod(out_path, 0755)
    else:
      os.symlink(os.path.join(root, f), out_path)
  for d in dirs:
    os.mkdir(os.path.join(out_dir, relroot, d))

print "Created JAVA_HOME facade in", out_dir
