#!/usr/bin/env bash

DIR="$( cd "$( dirname "$0" )" && pwd )"

# Maven
tar xzf $DIR/apache-maven-3.3.3-bin.tar.gz
# Minimal Maven repository
tar xzf $DIR/maven-3.3.3-skeleton-repo.tar.gz
mkdir -p .m2/repository
cp -nr maven-3.3.3-skeleton-repo/* .m2/repository/
rm -rf maven-3.3.3-skeleton-repo
