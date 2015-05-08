#!/bin/bash

virtualenv env
for package in jinja2 cherrypy beanstalkc MySQL-python boto PyYAML; do
  ./env/bin/pip install $package
done
