#!/bin/bash

virtualenv slave-env
for package in beanstalkc MySQL-python boto ; do
  ./slave-env/bin/pip install $package
done
virtualenv --relocatable slave-env

virtualenv server-env
for package in jinja2 cherrypy beanstalkc MySQL-python boto PyYAML; do
  ./server-env/bin/pip install $package
done
virtualenv --relocatable server-env
