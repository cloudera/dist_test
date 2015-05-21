#!/usr/bin/env python

import beanstalkc
import boto
import dist_test
import errno
import fcntl
import logging
import os
import re
import select
try:
  import simplejson as json
except:
  import json
import subprocess
import time

RUN_ISOLATED_OUT_RE = re.compile(r'\[run_isolated_out_hack\](.+?)\[/run_isolated_out_hack\]')

class Slave(object):
  def __init__(self):
    self.config = dist_test.Config()
    self.task_queue = dist_test.TaskQueue(self.config)
    self.results_store = dist_test.ResultsStore(self.config)
    self.cache_dir = self._get_exclusive_cache_dir()

  def _get_exclusive_cache_dir(self):
    for i in xrange(0, 16):
      dir = "%s.%d" % (self.config.ISOLATE_CACHE_DIR, i)
      if not os.path.isdir(dir):
        os.makedirs(dir)
      self._lockfile = file(os.path.join(dir, "lock"), "w")
      try:
        fcntl.lockf(self._lockfile.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
      except IOError, e:
        if e.errno in (errno.EACCES, errno.EAGAIN):
          logging.info("Another slave already using cache dir %s", dir)
          self._lockfile.close()
          continue
        raise
      # Succeeded in locking
      logging.info("Acquired lock on cache dir %s", dir)
      return dir
    raise Exception("Unable to lock any cache dir %s.<int>" %
        self.config.ISOLATE_CACHE_DIR)

  def _set_flags(self, f):
    fd = f.fileno()
    fl = fcntl.fcntl(fd, fcntl.F_GETFL)
    fcntl.fcntl(fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)

  def run_task(self, task, bs_job):
    cmd = [os.path.join(self.config.ISOLATE_HOME, "run_isolated.py"),
           "--isolate-server=%s" % self.config.ISOLATE_SERVER,
           "--cache=%s" % self.cache_dir,
           "--verbose",
           "--hash", task.task.isolate_hash]
    logging.info("Running command: %s", repr(cmd))
    self.results_store.mark_task_running(task.task)
    p = subprocess.Popen(
      cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    pipes = [p.stdout, p.stderr]
    self._set_flags(p.stdout)
    self._set_flags(p.stderr)

    stdout = ""
    stderr = ""

    timeout = task.task.timeout
    last_touch = time.time()
    start_time = last_touch
    while True:
      rlist, wlist, xlist = select.select(pipes, [], pipes, 2)
      if p.stdout in rlist:
        x = p.stdout.read(1024 * 1024)
        stdout += x
      if p.stderr in rlist:
        stderr += p.stderr.read(1024 * 1024)
      if xlist or p.poll() is not None:
        break
      now = time.time()
      if timeout > 0 and now > start_time + timeout:
        logging.info("Task timed out: " + task.task.description)
        stderr += "\n------\nKilling task after %d seconds" % timeout
        p.kill()
      if time.time() - last_touch > 10:
        logging.info("Still running: " + task.task.description)
        try:
          bs_job.touch()
        except:
          pass
        last_touch = time.time()

    rc = p.wait()

    output_archive_hash = None
    m = RUN_ISOLATED_OUT_RE.search(stdout)
    if m:
      isolated_out = json.loads(m.group(1))
      output_archive_hash = isolated_out['hash']

    self.results_store.mark_task_finished(task.task,
                                          output_archive_hash=output_archive_hash,
                                          result_code=p.wait(),
                                          stdout=stdout,
                                          stderr=stderr)

  def run(self):
    while True:
      try:
        task = self.task_queue.reserve_task()
      except Exception, e:
        logging.warning("Failed to reserve job: %s" % str(e))
        time.sleep(1)
        continue
      logging.info("got task: %s", task.task.to_json())
      self.run_task(task, task.bs_elem)
      try:
        task.bs_elem.delete()
      except Exception, e:
        logging.warning("Failed to delete job: %s" % str(e))
        continue


def main():
  logging.basicConfig(level=logging.INFO)
  Slave().run()

if __name__ == "__main__":
  main()
