#!/bin/bash

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

# Need to echo the correct path here, something like:
# exec /home/todd/sw/jdk1.8.0_45/jre/bin/java "$@"
