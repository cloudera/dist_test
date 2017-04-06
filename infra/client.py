#!/usr/bin/env python

from __future__ import with_statement
import contextlib
import getpass
import logging
import multiprocessing
from multiprocessing.pool import ThreadPool
import optparse
import os
import socket
import sys
import time
import urllib
import urllib2
try:
  import simplejson as json
except:
  import json
import time
import zipfile

import config

config = config.Config()
config.ensure_dist_test_configured()
TEST_MASTER = config.DIST_TEST_MASTER
LAST_JOB_PATH = config.DIST_TEST_JOB_PATH
RED = "\x1b[31m"
YELLOW = "\x1b[33m"
GREEN = "\x1b[32m"
RESET = "\x1b[m"

# Set a relatively long socket timeout, but short enough
# that if the server side is completely hung, we won't
# hang forever.
SOCKET_TIMEOUT_SECS = 60

LOG = logging.getLogger('dist_test.client')
LOG.setLevel(logging.INFO)

def is_tty():
  return hasattr(sys.stdout, 'isatty') and sys.stdout.isatty()

def ontty(msg):
  if is_tty():
    return msg
  return ""

def generate_job_id():
  return "%s.%d.%d" % (getpass.getuser(), int(time.time()), os.getpid())


def make_url(path):
  assert path.startswith("/")
  return TEST_MASTER.rstrip("/") + path


def print_status(start_time, previous_result, result, first=False, retcode=None):
  # In non-interactive mode, do not print unless the result changed
  if not is_tty() and previous_result is not None:
    if previous_result['finished_tasks'] == result['finished_tasks']:
      return

  # In interactive mode, delete the previous line of output after the first
  if not first:
    sys.stdout.write(ontty("\x1b[F\x1b[2K"))

  run_time = time.time() - start_time
  if retcode is not None:
    if retcode == 0:
      sys.stdout.write(ontty(GREEN))
    else:
      sys.stdout.write(ontty(RED))

  sys.stdout.write(" %.1fs\t" % run_time)

  sys.stdout.write(" %d/%d tests complete" % \
      (result['finished_groups'], result['total_groups']))

  if retcode is not None:
    sys.stdout.write(ontty(RESET))

  if result['failed_groups']:
    p = " (%d failed)" % result['failed_groups']
    sys.stdout.write(ontty(RED) + p + ontty(RESET))

  if result['retried_tasks']:
    p = " (%d retries)" % result['retried_tasks']
    sys.stdout.write(ontty(YELLOW) + p + ontty(RESET))

  sys.stdout.write("\n")
  sys.stdout.flush()


def get_return_code(result):
  retcode = None
  if result['status'] == "finished":
    if result['failed_groups'] > 0:
      retcode = 88
    else:
      retcode = 0
  return retcode


def urlopen_with_retry(*args, **kwargs):
  max_attempts = 10
  sleep_time = 5
  attempt = 0

  while True:
    try:
      return urllib2.urlopen(*args, **kwargs)
    except Exception:
      if attempt == max_attempts:
          raise
      attempt += 1
      LOG.info("Failed to contact server, will retry in %d seconds (attempt %d of %d)",
               sleep_time, attempt, max_attempts)
      time.sleep(sleep_time)


def do_watch_results(job_id):
  watch_url = make_url("/job?" + urllib.urlencode([("job_id", job_id)]))
  LOG.info("Watch your results at %s", watch_url)

  url = make_url("/job_status?" + urllib.urlencode([("job_id", job_id)]))
  start_time = time.time()

  first = True
  previous_result = None
  while True:
    result_str = urlopen_with_retry(url).read()
    result = json.loads(result_str)

    retcode = get_return_code(result)
    print_status(start_time, previous_result, result, first=first, retcode=retcode)
    first = False

    previous_result = result

    # Set and return a UNIX return code if we're finished, based on the test result
    if retcode is not None:
      return retcode

    # Sleep until next interval
    time.sleep(0.5)

def save_last_job_id(job_id):
  with file(LAST_JOB_PATH, "w") as f:
    f.write(job_id)

def load_last_job_id():
  try:
    with file(LAST_JOB_PATH, "r") as f:
      return f.read()
  except Exception:
    return None

def submit_job_json(job_prefix, job_json):
  # Verify that it is proper JSON
  json.loads(job_json)
  # Prepend the job_prefix if present
  if job_prefix is not None and len(job_prefix) > 0:
    job_prefix += "."
  job_id = job_prefix + generate_job_id()
  form_data = urllib.urlencode({'job_id': job_id, 'job_json': job_json})
  url = make_url("/submit_job")
  LOG.info("Submitting job to " + url)
  result_str = urlopen_with_retry(url, data=form_data).read()
  result = json.loads(result_str)
  if result.get('status') != 'SUCCESS':
    sys.err.println("Unable to submit job: %s" % repr(result))
    sys.exit(1)

  save_last_job_id(job_id)

  LOG.info("Submitted job %s", job_id)
  return job_id

def submit(argv):
  p = optparse.OptionParser(
      usage="usage: %prog submit [options] <job-json-path>")
  p.add_option("-n", "--name",
               action="store",
               type="string",
               dest="name",
               default="",
               help="Job name prefix, will be mangled for additional uniqueness")
  p.add_option("-d", "--output-dir", dest="out_dir", type="string",
               help="directory into which to download logs", metavar="PATH",
               default="dist-test-results")
  p.add_option("-l", "--logs", dest="logs", action="store_true", default=False,
               help="Whether to download logs")
  p.add_option("-a", "--artifacts", dest="artifacts", action="store_true", default=False,
               help="Whether to download artifacts")
  p.add_option("--no-wait", dest="no_wait", action="store_true", default=False,
               help="Exit after submitting the job, rather than waiting for completion")
  options, args = p.parse_args()

  if len(args) != 1:
    p.print_help()
    sys.exit(1)

  job_id = submit_job_json(options.name, file(args[0]).read())
  if options.no_wait:
    sys.exit(0)
  retcode = do_watch_results(job_id)
  if options.artifacts:
    _fetch(job_id, **vars(options))
  # print job_id to stdout, so the caller process (grind) can have it
  print 'job_id=%s' % job_id
  sys.exit(retcode)

def get_job_id_from_args(command, args):
  if len(args) == 1:
    job_id = load_last_job_id()
    if job_id is not None:
      LOG.info("Using most recently submitted job id: %s" % job_id)
      return job_id
  if len(args) != 2:
    print >>sys.stderr, "usage: %s %s <job-id>" % (os.path.basename(sys.argv[0]), command)
    sys.exit(1)
  return args[1]

def watch(argv):
  job_id = get_job_id_from_args("watch", argv)
  ret = 1
  try:
    ret = do_watch_results(job_id)
  except KeyboardInterrupt:
    pass
  sys.exit(ret)

def fetch_tasks(job_id, status=None):
  params = {"job_id": job_id}
  if status is not None:
    params["status"] = status
  url = make_url("/tasks?" + urllib.urlencode(params))
  results_str = urlopen_with_retry(url).read()
  return json.loads(results_str)

def safe_name(s):
  return "".join([c.isalnum() and c or "_" for c in str(s)])

def fetch(argv):
  p = optparse.OptionParser(
      usage="usage: %prog fetch [options] [job-id]")
  p.add_option("-d", "--output-dir", dest="out_dir", type="string",
               help="directory into which to download logs", metavar="PATH",
               default="dist-test-results")
  p.add_option("-l", "--logs", dest="logs", action="store_true", default=False,
               help="Whether to download logs", metavar="PATH")
  p.add_option("-a", "--artifacts", dest="artifacts", action="store_true", default=False,
               help="Whether to download artifacts", metavar="PATH")
  p.add_option("-f", "--failed-only", dest="failed_only", action="store_true",
               help="Download artifacts/logs only from failed tasks.")

  options, args = p.parse_args()

  if len(args) == 0:
    last_job = load_last_job_id()
    if last_job:
      args.append(last_job)

  if len(args) != 1:
    p.error("no job id specified")
  job_id = args[0]

  if not options.logs and not options.artifacts:
    p.error("Need to specify either --logs or --artifacts")

  _fetch(job_id, **vars(options))

def _fetch(job_id, out_dir, artifacts=False, logs=False, failed_only=False, **kwargs):
  # Fetch the finished tasks for the job
  status = failed_only and 'failed' or 'finished'
  tasks = fetch_tasks(job_id, status=status)
  if len(tasks) == 0:
    LOG.info("No tasks in specified job, or job does not exist")
    return
  # Attempt to make the output directory
  try:
    os.makedirs(out_dir)
  except Exception:
    pass
  # Collect links, download at the end
  log_links = []
  log_paths = []
  artifact_links = []
  artifact_paths = []
  for t in tasks:
    filename_prefix = ".".join((safe_name(t['task_id']), safe_name(t['attempt']), safe_name(t['description'])))
    path_prefix = os.path.join(out_dir, filename_prefix)
    if logs:
      if 'stdout_link' in t:
        path = path_prefix + ".stdout"
        log_links.append(t['stdout_link'])
        log_paths.append(path)
      else:
        LOG.info("No stdout for task %s" % t['task_id'])
      if 'stderr_link' in t:
        path = path_prefix + ".stderr"
        log_links.append(t['stderr_link'])
        log_paths.append(path)
      else:
        LOG.info("No stderr for task %s" % t['task_id'])
    if artifacts:
      if 'artifact_archive_link' in t:
        path = path_prefix + ".zip"
        artifact_links.append(t['artifact_archive_link'])
        artifact_paths.append(path)

  if logs:
    LOG.info("Fetching %d logs into %s",
                len(log_links),
                out_dir)
    _parallel_download(log_links, log_paths)

  if artifacts:
    LOG.info("Fetching %d artifacts into %s",
                len(artifact_links),
                out_dir)
    _parallel_download(artifact_links, artifact_paths)
    LOG.info("Extracting %d artifacts into %s",
                len(artifact_links),
                out_dir)
    _parallel_extract(artifact_paths, out_dir)

def _download(link, path):
  max_attempts = 10
  for x in range(max_attempts):
    try:
      if not os.path.exists(path):
        LOG.debug("Fetching %s into %s", link, path)
        urllib.urlretrieve(link, path)
        return path
      else:
        LOG.debug("Skipping already downloaded path %s" % path)
    except Exception as e:
      # Remove possible partially downloaded file
      if os.path.exists(path):
        os.remove(path)
      if x < max_attempts - 1:
        LOG.info("Retrying download of %s to %s" % (link, path))
        time.sleep(5)
      else:
        raise

def _parallel_download(links, paths):
  pool = ThreadPool(processes=int(multiprocessing.cpu_count()*1.5))
  results = []
  for link, path in zip(links, paths):
    results.append(pool.apply_async(_download, (link, path)))
  for r in results:
    try:
      while True:
        # This goofy loop with a timeout ensures that we handle KeyboardInterrupt.
        # Otherwise, KeyboardInterrupt won't get caught.
        try:
          r.get(timeout=1)
          break
        except multiprocessing.TimeoutError:
          continue
    except Exception as e:
      raise

def _extract(path, out_dir):
  # Use the zipfile's basename for uniqueness
  zipname = os.path.basename(path)
  assert zipname.endswith(".zip")
  zipname = zipname[:-len(".zip")]
  dest_path = os.path.join(out_dir, zipname)
  if not os.path.exists(dest_path):
    os.makedirs(dest_path)
    LOG.debug("Extracting %s into %s", path, dest_path)
    try:
      with contextlib.closing(zipfile.ZipFile(path, "r")) as myzip:
        for info in myzip.infolist():
            myzip.extract(info, dest_path)
    except Exception as e:
      print >> sys.stderr, "Error extracting %s: %s" % (path, e)
      raise

  else:
    LOG.debug("Skipping extracting %s, destination already exists" % path)

def _parallel_extract(paths, out_dir):
  pool = multiprocessing.Pool(processes=multiprocessing.cpu_count())
  results = []
  for path in paths:
    results.append(pool.apply_async(_extract, (path, out_dir)))
  for r in results:
    try:
      r.get()
    except Exception as e:
      print >> sys.stderr, "Error during extraction: %s" % e

def cancel_job(argv):
  job_id = get_job_id_from_args("cancel", argv)
  url = make_url("/cancel_job?" + urllib.urlencode([("job_id", job_id)]))
  result_str = urlopen_with_retry(url).read()
  LOG.info("Cancellation: %s" % result_str)

def usage(argv):
  print >>sys.stderr, "usage: %s <command> [<args>]" % os.path.basename(argv[0])
  print >>sys.stderr, """Commands:
    submit  Submit a JSON file listing tasks
    cancel  Cancel a previously submitted job
    watch   Watch an already-submitted job ID
    fetch   Fetch test logs and artifacts from a previous job"""
  print >>sys.stderr, "%s <command> --help may provide further info" % argv[0]


def main(argv):
  if len(argv) < 2:
    usage(argv)
    sys.exit(1)

  config.configure_auth()
  socket.setdefaulttimeout(SOCKET_TIMEOUT_SECS)
  command = argv[1]
  del argv[1]
  if command == "submit":
    submit(argv)
  elif command == "watch":
    watch(argv)
  elif command == "cancel":
    cancel_job(argv)
  elif command == "fetch":
    fetch(argv)
  else:
    usage(argv)
    sys.exit(1)

if __name__ == "__main__":
  main(sys.argv)
