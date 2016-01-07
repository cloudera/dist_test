#!/bin/bash

virtualenv slave-env
for package in beanstalkc PyYAML MySQL-python boto glob2; do
  ./slave-env/bin/pip install $package
done
virtualenv --relocatable slave-env

virtualenv server-env
for package in jinja2 cherrypy beanstalkc MySQL-python boto PyYAML simple_json; do
  ./server-env/bin/pip install $package
done
virtualenv --relocatable server-env
