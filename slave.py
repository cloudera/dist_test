#!/usr/bin/env python

import beanstalkc
import dist_test
import logging
import os
import simplejson
import subprocess

class Slave(object):
  def __init__(self):
    self.config = dist_test.Config()
    self.task_queue = dist_test.TaskQueue(self.config)
    self.results_store = dist_test.ResultsStore(self.config)

  def run_task(self, task):
    cmd = [os.path.join(self.config.ISOLATE_HOME, "run_isolated.py"),
       "run_isolated.py",
       "--isolate-server=%s" % self.config.ISOLATE_SERVER,
       "--cache=%s" % self.config.ISOLATE_CACHE_DIR,
       "--hash", task.task.isolate_hash]
    logging.info("Running command: %s", repr(cmd))
    p = subprocess.Popen(
      cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout, stderr = p.communicate()
    print "out: ", stdout
    print "err: ", stderr
    self.results_store.mark_task_finished(task.task,
                                          result_code=p.wait(),
                                          stdout=stdout,
                                          stderr=stderr)

  def run(self):
    while True:
      task = self.task_queue.reserve_task()
      logging.info("got task: %s", task.task.to_json())
      self.run_task(task)
      task.bs_elem.delete()


def main():
  logging.basicConfig(level=logging.INFO)
  Slave().run()

if __name__ == "__main__":
  main()
