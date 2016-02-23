#!/bin/bash

virtualenv slave-env
for package in beanstalkc MySQL-python boto glob2 google-api-python-client oauth2client==1.5.2; do
  ./slave-env/bin/pip install --upgrade $package
done
virtualenv --relocatable slave-env
