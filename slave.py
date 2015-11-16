#!/usr/bin/env python

from __future__ import with_statement
import beanstalkc
import boto
import cStringIO
import errno
import fcntl
import glob2
import logging
import os
import urllib
import urllib2
import re
import select
import shutil
import sys
try:
  import simplejson as json
except:
  import json
import subprocess
import threading
import time
import zipfile

from config import Config
import dist_test

import metrics

RUN_ISOLATED_OUT_RE = re.compile(r'\[run_isolated_out_hack\](.+?)\[/run_isolated_out_hack\]',
                                 re.DOTALL)
LOG = None

# Number of seconds over which to compute the load average for metrics.
# The load average is the percentage of time over the last N seconds
# during which the slave was running a job.
NUM_SECONDS_LOAD_AVERAGE = 30

class Slave(object):

  def __init__(self, config):
    self.config = config
    self.config.ensure_isolate_configured()
    self.config.ensure_dist_test_configured()
    self.task_queue = dist_test.TaskQueue(self.config)
    self.results_store = dist_test.ResultsStore(self.config)
    self.cache_dir = self._get_exclusive_cache_dir()
    self.metrics_collector = metrics.MetricsCollector()
    self.is_busy = False

  def _get_exclusive_cache_dir(self):
    for i in xrange(0, 16):
      dir = "%s.%d" % (self.config.ISOLATE_CACHE_DIR, i)
      if not os.path.isdir(dir):
        os.makedirs(dir)
      self._lockfile = file(dir + ".lock", "w")
      try:
        fcntl.lockf(self._lockfile.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
      except IOError, e:
        if e.errno in (errno.EACCES, errno.EAGAIN):
          LOG.info("Another slave already using cache dir %s", dir)
          self._lockfile.close()
          continue
        raise
      # Succeeded in locking
      LOG.info("Acquired lock on cache dir %s", dir)
      return dir
    raise Exception("Unable to lock any cache dir %s.<int>" %
        self.config.ISOLATE_CACHE_DIR)

  def _set_flags(self, f):
    fd = f.fileno()
    fl = fcntl.fcntl(fd, fcntl.F_GETFL)
    fcntl.fcntl(fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)

  def parse_test_dir(self, stderr):
    # Find the test_dir for this invocation of run_isolated.py
    # FIXME: this is done by parsing the stderr of invoking run_isolated.py, which is
    # far from bullet-proof.
    #
    # Example:
    # WARNING   3420    run_isolated(197): Deliberately leaking /tmp/run_tha_test1r2oKG for later examination
    test_dir = None
    pattern = re.compile(r"WARNING[ ]+[\d]+[ ]+run_isolated.*: Deliberately leaking (.*) for later examination")
    for line in stderr.splitlines():
      m = pattern.match(line)
      if m is not None:
        test_dir = m.group(1)
        # Do not break early, we want the last stderr line that matches

    if test_dir is None:
      LOG.warn("No run_tha_test directory found!")
      return None
    if not os.path.exists(test_dir):
      LOG.warn("Parsed run_tha_test directory %s does not actually exist!" % test_dir)
      return None

    return test_dir

  def make_archive(self, task, test_dir):
    # Return early if no test_dir is specified
    if test_dir is None:
      return None
    # Return early if there are no globs specified
    if task.task.artifact_archive_globs is None or len(task.task.artifact_archive_globs) == 0:
      return None
    all_matched = set()
    total_size = 0
    for g in task.task.artifact_archive_globs:
      try:
          matched = glob2.iglob(test_dir + "/" + g)
          for m in matched:
            canonical = os.path.realpath(m)
            if not canonical.startswith(test_dir):
              LOG.warn("Glob %s matched file outside of test_dir, skipping: %s" % (g, canonical))
              continue
            total_size += os.stat(canonical).st_size
            all_matched.add(canonical)
      except Exception as e:
        LOG.warn("Error while globbing %s: %s" % (g, e))

    if len(all_matched) == 0:
      return None
    max_size = 200*1024*1024 # 200MB max uncompressed size
    if total_size > max_size:
      # If size exceeds the maximum size, upload a zip with an error message instead
      LOG.info("Task %s generated too many bytes of matched artifacts (%d > %d)," \
               + "uploading archive with error message instead.",
              task.task.get_id(), total_size, max_size)
      archive_buffer = cStringIO.StringIO()
      with zipfile.ZipFile(archive_buffer, "w") as myzip:
        myzip.writestr("_ARCHIVE_TOO_BIG_",
                       "Size of matched uncompressed test artifacts exceeded maximum size" \
                       + "(%d bytes > %d bytes)!" % (total_size, max_size))
      return archive_buffer

    # Write out the archive
    archive_buffer = cStringIO.StringIO()
    with zipfile.ZipFile(archive_buffer, "w") as myzip:
      for m in all_matched:
        arcname = os.path.relpath(m, test_dir)
        while arcname.startswith("/"):
          arcname = arcname[1:]
        myzip.write(m, arcname)

    return archive_buffer


  def run_task(self, task, bs_job):
    cmd = [os.path.join(self.config.ISOLATE_HOME, "run_isolated.py"),
           "--isolate-server=%s" % self.config.ISOLATE_SERVER,
           "--cache=%s" % self.cache_dir,
           "--verbose",
           "--leak-temp",
           "--hash", task.task.isolate_hash]
    if not self.results_store.mark_task_running(task.task):
      LOG.info("Task %s canceled", task.task.description)
      return
    LOG.info("Running command: %s", repr(cmd))
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
    kill_term_time = start_time + timeout
    kill_kill_time = kill_term_time + 5
    while True:
      rlist, wlist, xlist = select.select(pipes, [], pipes, 2)
      if p.stdout in rlist:
        x = p.stdout.read(1024 * 1024)
        stdout += x
      if p.stderr in rlist:
        x = p.stderr.read(1024 * 1024)
        stderr += x
      if xlist or p.poll() is not None:
        break
      now = time.time()
      if timeout > 0 and now > kill_term_time:
        LOG.info("Task timed out: " + task.task.description)
        stderr += "\n------\nKilling task after %d seconds" % timeout
        p.terminate()
      if timeout > 0 and now > kill_kill_time:
        LOG.info("Task did not exit after SIGTERM. Sending SIGKILL")
        p.kill()

      if time.time() - last_touch > 10:
        LOG.info("Still running: " + task.task.description)
        self.submit_load_metric(1)
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

    test_dir = self.parse_test_dir(stderr)
    artifact_archive = None

    # Don't upload logs from successful builds
    if rc == 0:
      stdout = None
      stderr = None

    artifact_archive = self.make_archive(task, test_dir)

    end_time = time.time()
    duration_secs = end_time - start_time

    self.results_store.mark_task_finished(task.task,
                                          output_archive_hash=output_archive_hash,
                                          result_code=rc,
                                          stdout=stdout,
                                          stderr=stderr,
                                          artifact_archive=artifact_archive,
                                          duration_secs=duration_secs)

    # Do cleanup of temp files
    if test_dir is not None:
      LOG.info("Removing test directory %s" % test_dir)
      shutil.rmtree(test_dir)
    if artifact_archive is not None:
      artifact_archive.close()

    # Retry if non-zero exit code and have retries remaining
    if rc != 0 and task.task.attempt < task.task.max_retries:
      self.submit_retry_task(task.task.to_json())

  def submit_retry_task(self, task_json):
    form_data = urllib.urlencode({'task_json': task_json})
    url = self.config.DIST_TEST_MASTER + "/retry_task"
    result_str = urllib2.urlopen(url, data=form_data).read()
    result = json.loads(result_str)
    if result.get('status') != 'SUCCESS':
      sys.err.println("Unable to submit retry task: %s" % repr(result))

  def submit_load_metric(self, load):
    try:
      self.metrics_collector.submit(load)
    except Exception, e:
      logging.warning("Failed to submit load metric: %s" % str(e))

  def run_metrics_thread(self):
    ring_buffer = [False for x in range(NUM_SECONDS_LOAD_AVERAGE)]
    i = 0
    while True:
      ring_buffer[i % len(ring_buffer)] = self.is_busy
      i += 1
      load = sum(ring_buffer) / float(len(ring_buffer))
      time.sleep(1)
      if i % 10 == 0:
        self.submit_load_metric(load)

  def run(self):
    metrics_thread = threading.Thread(target=self.run_metrics_thread)
    metrics_thread.daemon = True
    metrics_thread.start()
    while True:
      try:
        logging.info("waiting for next task...")
        self.is_busy = False
        task = self.task_queue.reserve_task()
      except Exception, e:
        LOG.warning("Failed to reserve job: %s" % str(e))
        time.sleep(1)
        continue
      LOG.info("got task: %s", task.task.to_json())
      self.is_busy = True
      self.run_task(task, task.bs_elem)
      try:
        logging.info("task complete")
        task.bs_elem.delete()
      except Exception, e:
        LOG.warning("Failed to delete job: %s" % str(e))
        continue


def main():
  global LOG

  config = Config()
  LOG = logging.getLogger('dist_test.slave')
  dist_test.configure_logger(LOG, config.SLAVE_LOG)

  LOG.info("Starting slave")
  Slave(config).run()

if __name__ == "__main__":
  main()
