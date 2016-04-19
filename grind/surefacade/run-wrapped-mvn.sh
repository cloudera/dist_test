#!/bin/bash
PATH=$1/bin:$PATH mvn test -Djava.home=$1/jre -DforkCount=4 -DreuseForks=true
