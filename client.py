#!/usr/bin/env python

import getpass
import logging
import multiprocessing
import optparse
import os
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

RED = "\x1b[31m"
YELLOW = "\x1b[33m"
GREEN = "\x1b[32m"
RESET = "\x1b[m"

LOG = logging.getLogger('dist_test.client')
LOG.setLevel(logging.INFO)

def generate_job_id():
  return "%s.%d.%d" % (getpass.getuser(), int(time.time()), os.getpid())

def print_status(start_time, previous_result, result,
                 interactive=False, first=False, retcode=None):
  # In non-interactive mode, do not print unless the result changed
  if not interactive and previous_result is not None:
    if previous_result['finished_tasks'] == result['finished_tasks']:
      return

  # In interactive mode, delete the previous line of output after the first
  if interactive and not first:
    sys.stdout.write("\x1b[F\x1b[2K")

  run_time = time.time() - start_time
  if interactive and retcode is not None:
    if retcode == 0:
      sys.stdout.write(GREEN)
    else:
      sys.stdout.write(RED)

  sys.stdout.write(" %.1fs\t" % run_time)

  sys.stdout.write(" %d/%d tests complete" % \
      (result['finished_groups'], result['total_groups']))

  if interactive and retcode is not None:
    sys.stdout.write(RESET)

  if result['failed_groups']:
    p = " (%d failed)" % result['failed_groups']
    if interactive:
      sys.stdout.write(RED + p + RESET)
    else:
      sys.stdout.write(p)

  if result['retried_tasks']:
    p = " (%d retries)" % result['retried_tasks']
    if interactive:
      sys.stdout.write(YELLOW + p + RESET)
    else:
      sys.stdout.write(p)

  sys.stdout.write("\n")


def get_return_code(result):
  retcode = None
  if result['finished_tasks'] == result['total_tasks']:
    if result['failed_groups'] > 0:
      retcode = 88
    else:
      retcode = 0
  return retcode


def do_watch_results(job_id):
  watch_url = TEST_MASTER + "/job?" + urllib.urlencode([("job_id", job_id)])
  LOG.info("Watch your results at %s", watch_url)

  url = TEST_MASTER + "/job_status?" + urllib.urlencode([("job_id", job_id)])
  start_time = time.time()

  # We can detect a non-interactive Jenkins environment by checking for BUILD_ID
  interactive = "BUILD_ID" not in os.environ.keys()
  first = True
  previous_result = None
  while True:
    result_str = urllib2.urlopen(url).read()
    result = json.loads(result_str)

    retcode = get_return_code(result)
    print_status(start_time, previous_result, result, interactive=interactive, first=first, retcode=retcode)
    first = False

    previous_result = result

    # Set and return a UNIX return code if we're finished, based on the test result
    if retcode is not None:
      return retcode

    # Sleep until next interval
    time.sleep(0.5)

def save_last_job_id(job_id):
  with file(os.path.expanduser("~/.dist-test-last-job"), "w") as f:
    f.write(job_id)

def load_last_job_id():
  try:
    with file(os.path.expanduser("~/.dist-test-last-job"), "r") as f:
      return f.read()
  except:
    return None

def submit_job_json(job_prefix, job_json):
  # Verify that it is proper JSON
  json.loads(job_json)
  # Prepend the job_prefix if present
  if job_prefix is not None and len(job_prefix) > 0:
    job_prefix += "."
  job_id = job_prefix + generate_job_id()
  form_data = urllib.urlencode({'job_id': job_id, 'job_json': job_json})
  result_str = urllib2.urlopen(TEST_MASTER + "/submit_job",
                               data=form_data).read()
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
               help="Whether to download logs", metavar="PATH")
  p.add_option("-a", "--artifacts", dest="artifacts", action="store_true", default=False,
               help="Whether to download artifacts", metavar="PATH")
  options, args = p.parse_args()

  if len(args) != 1:
    p.print_help()
    sys.exit(1)

  job_id = submit_job_json(options.name, file(args[0]).read())
  retcode = do_watch_results(job_id)
  if options.artifacts:
    _fetch(job_id, options.artifacts, options.logs, options.out_dir)
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
  sys.exit(do_watch_results(job_id))

def fetch_tasks(job_id, status=None):
  params = {"job_id": job_id}
  if status is not None:
    params["status"] = status
  url = TEST_MASTER + "/tasks?" + urllib.urlencode(params)
  results_str = urllib2.urlopen(url).read()
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

  _fetch(job_id, options.artifacts, options.logs, options.out_dir)

def _fetch(job_id, artifacts, logs, out_dir):
  # Fetch the finished tasks for the job
  tasks = fetch_tasks(job_id, status="finished")
  if len(tasks) == 0:
    LOG.info("No tasks in specified job, or job does not exist")
    return
  # Attempt to make the output directory
  try:
    os.makedirs(out_dir)
  except:
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
  for x in range(3):
    try:
      if not os.path.exists(path):
        LOG.debug("Fetching %s into %s", link, path)
        urllib.urlretrieve(link, path)
        return path
      else:
        LOG.debug("Skipping already downloaded path %s" % path)
    except Exception as e:
      LOG.info("Retrying download of %s to %s" % (link, path))
      # Remove possible partially downloaded file
      if os.path.exists(path):
        os.remove(path)

def _parallel_download(links, paths):
  pool = multiprocessing.Pool(processes=int(multiprocessing.cpu_count()*1.5))
  results = []
  for link, path in zip(links, paths):
    results.append(pool.apply_async(_download, (link, path)))
  for r in results:
    try:
      r.get()
    except Exception as e:
      pass

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
      with zipfile.ZipFile(path, "r") as myzip:
        for info in myzip.infolist():
            myzip.extract(info, dest_path)
    except Exception as e:
      print >> sys.stderr, "Error extracting %s: %s" % (path, e)

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
  url = TEST_MASTER + "/cancel_job?" + urllib.urlencode([("job_id", job_id)])
  result_str = urllib2.urlopen(url).read()
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
