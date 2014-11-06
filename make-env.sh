#!/bin/bash

virtualenv env
for package in jinja2 cherrypy beanstalkc MySQL-python; do
  ./env/bin/pip install $packaage
done
