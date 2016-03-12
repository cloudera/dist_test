#!/bin/bash

virtualenv server-env
for package in jinja2 cherrypy beanstalkc MySQL-python boto PyYAML simple_json netaddr==0.7.18; do
  ./server-env/bin/pip install $package
done
virtualenv --relocatable server-env
