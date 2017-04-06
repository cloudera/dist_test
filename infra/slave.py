#!/usr/bin/env python

from __future__ import with_statement
import beanstalkc
import boto
import collections
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
import signal
import subprocess
import sys
import threading
import time
import contextlib
import zipfile

from config import Config
import dist_test

RUN_ISOLATED_OUT_RE = re.compile(r'\[run_isolated_out_hack\](.+?)\[/run_isolated_out_hack\]',
                                 re.DOTALL)
LOG = None



class RetryCache(object):
  """Time-based and count-based cache to avoid running retried tasks
  again on the same slave. If a slave sees a retry it submitted, it
  puts it back into beanstalk and does a short sleep in the hope that
  another slave dequeues it.

  This cache tracks the number of times that a given task has been retried
  by this slave. When the number of times reaches a threshold, the task
  is evicted from the cache, letting the task run on the same slave.
  This prevents livelock.

  Otherwise, the cache is evicted based on oldest insertion time."""

  def __init__(self, max_size=100, max_count=10):
    """Create a new RetryCache.
    
    max_size: maximum number of items in the cache.
    max_count: maximum number of touches before an item expires."""
    self.cache = collections.OrderedDict()
    self.max_size = max_size
    self.max_count = max_count

  def get(self, item):
    if not item in self.cache.keys():
      return None
    count = self.cache[item]
    if count > self.max_count:
      LOG.debug("Item %s hit max_count of %d, evicting from cache", item, self.max_count)
      del self.cache[item]
    else:
      self.cache[item] += 1

    return item

  def put(self, item):
    if len(self.cache.keys()) == self.max_size:
      LOG.debug("Cache is at capacity %d, evicting oldest item %s", self.max_size, item)
      self.cache.popitem()
    self.cache[item] = 0

class Slave(object):

  def __init__(self, config):
    self.config = config
    self.config.ensure_isolate_configured()
    self.config.ensure_dist_test_configured()
    self.task_queue = dist_test.TaskQueue(self.config)
    self.results_store = dist_test.ResultsStore(self.config)
    self.cache_dir = self._get_exclusive_cache_dir()
    self.cur_task = None
    self.is_busy = False
    self.retry_cache = RetryCache()

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
      LOG.warn("test_dir not given, skipping archive")
      return None
    # Return early if there are no globs specified
    if task.task.artifact_archive_globs is None or len(task.task.artifact_archive_globs) == 0:
      LOG.warn("archive glob not given, skipping archive")
      return None
    all_matched = set()
    total_size = 0
    for g in task.task.artifact_archive_globs:
      try:
          matched = glob2.iglob(test_dir + "/" + g)
          for m in matched:
            canonical = os.path.realpath(m)
            if sys.platform != "darwin" and (not canonical.startswith(test_dir)): # work around on mac os
              LOG.warn("Glob %s matched file outside of test_dir %s, skipping: %s (sys=%s)" % (g, test_dir, canonical, sys.platform))
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
      with contextlib.closing(zipfile.ZipFile(archive_buffer , "w")) as myzip:
        myzip.writestr("_ARCHIVE_TOO_BIG_",
                       "Size of matched uncompressed test artifacts exceeded maximum size" \
                       + "(%d bytes > %d bytes)!" % (total_size, max_size))
      return archive_buffer

    # Write out the archive
    archive_buffer = cStringIO.StringIO()
    with contextlib.closing(zipfile.ZipFile(archive_buffer , "w", zipfile.ZIP_DEFLATED)) as myzip:
      for m in all_matched:
        arcname = os.path.relpath(m, test_dir)
        while arcname.startswith("/"):
          arcname = arcname[1:]
        myzip.write(m, arcname)

    return archive_buffer


  def run_task(self, task):
    cmd = [os.path.join(self.config.ISOLATE_HOME, "run_isolated.py"),
           "--isolate-server=%s" % self.config.ISOLATE_SERVER,
           "--cache=%s" % self.cache_dir,
           "--verbose",
           "--leak-temp",
           "--hash", task.task.isolate_hash]
    if not self.results_store.mark_task_running(task.task):
      LOG.info("Task %s canceled", task.task.description)
      return
    # Make run_isolated run in 'bot' mode. This prevents it from trying
    # to use oauth to authenticate.
    env = os.environ.copy()
    env['SWARMING_HEADLESS'] = '1'

    LOG.info("Running command: %s", repr(cmd))
    p = subprocess.Popen(
      cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
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
        try:
          task.bs_elem.touch()
        except:
          LOG.info("Could not touch beanstalk queue elem", exc_info=True)
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
      self.submit_retry_task(task)

  def submit_retry_task(self, task):
    task_json = task.task.to_json()
    form_data = urllib.urlencode({'task_json': task_json})
    url = self.config.DIST_TEST_MASTER + "/retry_task"
    result_str = urllib2.urlopen(url, data=form_data).read()
    result = json.loads(result_str)
    if result.get('status') != 'SUCCESS':
      sys.err.println("Unable to submit retry task: %s" % repr(result))
    # Add to the retry cache for anti-affinity
    self.retry_cache.put(task.task.get_retry_id())

  def handle_sigterm(self):
    logging.error("caught SIGTERM! shutting down")
    if self.cur_task is not None:
      logging.warning("releasing running job")
      self.cur_task.bs_elem.release()
    os._exit(0)

  def run(self):
    while True:
      try:
        logging.info("waiting for next task...")
        self.is_busy = False
        self.cur_task = self.task_queue.reserve_task()
      except Exception, e:
        LOG.warning("Failed to reserve job: %s" % str(e))
        time.sleep(1)
        continue

      LOG.info("got task: %s", self.cur_task.task.to_json())

      if self.retry_cache.get(self.cur_task.task.get_retry_id()) is not None:
        sleep_time = 5
        LOG.info("Got a retry task submitted by this slave, releasing it and sleeping %d s...", sleep_time)
        self.cur_task.bs_elem.release()
        time.sleep(sleep_time)
        continue

      self.is_busy = True
      self.run_task(self.cur_task)
      try:
        logging.info("task complete")
        self.cur_task.bs_elem.delete()
      except Exception, e:
        LOG.warning("Failed to delete job: %s" % str(e))
      finally:
        self.cur_task = None


def main():
  global LOG

  config = Config()
  LOG = logging.getLogger('dist_test.slave')
  dist_test.configure_logger(LOG, config.SLAVE_LOG)
  config.configure_auth()

  LOG.info("Starting slave")
  s = Slave(config)
  signal.signal(signal.SIGTERM, lambda sig, stack: s.handle_sigterm())
  s.run()

if __name__ == "__main__":
  main()
