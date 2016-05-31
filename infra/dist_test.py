import beanstalkc
import boto
from ConfigParser import SafeConfigParser
import errno
import logging
import MySQLdb
import os
import urllib
import uuid
try:
  import simplejson as json
except:
  import json
import socket
import threading

# We don't actually use 'yaml' here. But, without yaml available,
# beanstalkc will fall back to providing string results for stats()
# and stats_tube(). So, we import it just to make sure it's around.
import yaml
import config

class Task(object):
  """Serializable task description used for communicating tasks between
  server and slaves."""
  @staticmethod
  def from_json(json_str):
    return Task(json.loads(json_str))

  @staticmethod
  def create(job_id, isolate_hash, description):
    return Task(dict(job_id=job_id,
                     isolate_hash=isolate_hash,
                     description=description,
                     task_id=str(uuid.uuid1())))

  def __init__(self, d):
    self.job_id = d['job_id']
    self.task_id = d['task_id']
    self.isolate_hash = d['isolate_hash']
    self.description = d['description']
    self.timeout = d.get('timeout', 0)
    # The task attempt number. Starts at 0.
    self.attempt = d.get('attempt', 0)
    # The number of times this task will be retried.
    # The default value of 0 means the task will not be retried.
    self.max_retries = d.get('max_retries', 0)
    self.artifact_archive_globs = d.get('artifact_archive_globs', [])

  def to_json(self):
    job_struct = dict(
      job_id=self.job_id,
      task_id=self.task_id,
      isolate_hash=self.isolate_hash,
      description=self.description,
      timeout=self.timeout,
      attempt=self.attempt,
      max_retries=self.max_retries,
      artifact_archive_globs=self.artifact_archive_globs,
    )
    return json.dumps(job_struct)

  def get_retry_id(self):
    return "%s.%s" % (self.job_id, self.task_id)

  def get_id(self):
    return "%s.%s.%s" % (self.job_id, self.task_id, self.attempt)

class TaskGroup(object):
  """Calculate group-level status information about a set of tasks rows returned
  by fetch_task_rows_for_job"""

  def __init__(self, tasks):
    self.tasks = tasks
    # Compute group status
    # Reminder:
    #   any([]) => False
    #   all([]) => True
    failed = [t['status'] is not None and t['status'] != 0 for t in tasks]
    all_failed = all(failed) and len(failed) > 0
    any_failed = any(failed)
    has_retries_remaining = all([t['attempt'] != t['max_retries'] for t in tasks])
    any_succeeded = any([t['status'] == 0 for t in tasks])
    # Failed groups have all non-zero status codes and have used all their retries.
    # Flaky groups have at least one failure and one success, or have retries left.
    # Succeeded groups have at least one success.
    #
    # Failed/succeeded are mutually exclusive. Flakiness is not.
    self.is_failed = False
    self.is_flaky = False
    self.is_succeeded = False

    if all_failed:
      if has_retries_remaining:
        self.is_flaky = True
      else:
        self.is_failed = True
    elif any_succeeded:
      self.is_succeeded = True
      if any_failed:
        self.is_flaky = True

    # Group is finished either when it has a success, or is out of retries
    self.is_finished = False
    if any_succeeded or (all_failed and not has_retries_remaining):
      self.is_finished = True

class ReservedTask(object):
  def __init__(self, bs_elem):
    self.bs_elem = bs_elem
    self.task = Task.from_json(bs_elem.body)

class TaskQueue(object):
  def __init__(self, config):
    config.ensure_beanstalk_configured()
    self.bs = beanstalkc.Connection(config.BEANSTALK_HOST)
    # beanstalkc is not thread-safe
    self.lock = threading.Lock()

  def submit_task(self, task, priority=2147483648):
    """Submit a beanstalk task, with optional non-negative integer priority.
    Lower priority values are reserved first."""
    logging.info("Submitting task %s" % task.job_id)
    with self.lock:
      self.bs.put(task.to_json(), priority=priority)

  def reserve_task(self):
    with self.lock:
      bs_elem = self.bs.reserve()
    return ReservedTask(bs_elem)

  def stats(self):
    with self.lock:
      return self.bs.stats_tube("default")

class ResultsStore(object):
  def __init__(self, config):
    self.config = config
    self.config.ensure_aws_configured()
    self.config.ensure_mysql_configured()

    self.thread_local = threading.local()
    logging.info("Connected to MySQL at %s" % config.MYSQL_HOST)
    self._ensure_tables()

    self.s3 = boto.connect_s3(self.config.AWS_ACCESS_KEY, self.config.AWS_SECRET_KEY)
    self.s3_bucket = self.s3.get_bucket(self.config.AWS_TEST_RESULT_BUCKET)

    logging.info("Connected to S3 with access key %s" % self.config.AWS_ACCESS_KEY)

  def _execute_query(self, query, *args, **kwargs):
    """ Execute a query, automatically reconnecting on disconnection. """
    # We'll try up to 3 times to reconnect
    MAX_ATTEMPTS = 3

    # Error code for the "MySQL server has gone away" error.
    MYSQL_SERVER_GONE_AWAY = 2006

    attempt_num = 0
    while True:
      c = self._connect_mysql().cursor(MySQLdb.cursors.DictCursor)
      attempt_num = attempt_num + 1
      try:
        if kwargs.get('use_executemany', False):
          c.executemany(query, *args)
        else:
          c.execute(query, *args)
        return c
      except MySQLdb.OperationalError as err:
        if err.args[0] == MYSQL_SERVER_GONE_AWAY and attempt_num < MAX_ATTEMPTS:
          logging.warn("Forcing reconnect to MySQL: %s" % err)
          self.thread_local.db = None
          continue
        else:
          raise

  def _connect_mysql(self):
    if hasattr(self.thread_local, "db") and \
          self.thread_local.db is not None:
      return self.thread_local.db
    self.thread_local.db = MySQLdb.connect(
      self.config.MYSQL_HOST,
      self.config.MYSQL_USER,
      self.config.MYSQL_PWD,
      self.config.MYSQL_DB)
    logging.info("Connected to MySQL at %s" % self.config.MYSQL_HOST)
    self.thread_local.db.autocommit(True)
    return self.thread_local.db

  def _ensure_tables(self):
    self._execute_query("""
      CREATE TABLE IF NOT EXISTS dist_test_tasks (
        job_id varchar(100) not null,
        task_id varchar(100) not null,
        attempt tinyint not null default 0,
        max_retries tinyint not null default 0,
        description varchar(100) not null,
        submit_timestamp timestamp not null default current_timestamp,
        start_timestamp timestamp null,
        hostname varchar(100),
        complete_timestamp timestamp null,
        output_archive_hash char(40),
        stdout_abbrev varchar(100),
        stderr_abbrev varchar(100),
        stdout_key varchar(256),
        stderr_key varchar(256),
        artifact_archive_key varchar(256),
        status int,
        PRIMARY KEY(job_id, task_id, attempt),
        INDEX(submit_timestamp)
      );""")
    self._execute_query("""
      CREATE TABLE IF NOT EXISTS dist_test_durations (
        description varchar(100) not null primary key,
        task_id varchar(100) not null,
        duration_secs int not null
      );""")


  def register_tasks(self, tasks):
    tuples = []
    for task in tasks:
      tuples.append((task.job_id, task.task_id, task.attempt, task.max_retries, task.description))
    self._execute_query("""
      INSERT INTO dist_test_tasks(job_id, task_id, attempt, max_retries, description) VALUES (%s, %s, %s, %s, %s)
      """, tuples, use_executemany=True)

  def mark_task_running(self, task):
    parms = dict(job_id=task.job_id,
                 task_id=task.task_id,
                 attempt=task.attempt,
                 hostname=socket.gethostname())
    q = self._execute_query("""
      UPDATE dist_test_tasks SET
        start_timestamp=now(),
        hostname=%(hostname)s
      WHERE job_id = %(job_id)s AND task_id = %(task_id)s AND attempt = %(attempt)s
      AND status IS NULL""", parms)
    return q.rowcount > 0


  def cancel_job(self, job_id):
    parms = dict(result_code=-1,
                 job_id=job_id,
                 stderr_abbrev="[canceled]")
    self._execute_query("""
      UPDATE dist_test_tasks SET
        status = %(result_code)s,
        stderr_abbrev = %(stderr_abbrev)s,
        complete_timestamp = now()
      WHERE job_id = %(job_id)s AND status IS NULL""", parms)
    
  def mark_task_finished(self, task, result_code, stdout, stderr, artifact_archive, output_archive_hash, duration_secs):
    stdout_key = None
    stdout_abbrev = ""
    stderr_key = None
    stderr_abbrev = ""
    artifact_archive_key = None

    if stdout:
      stdout_key = "%s.stdout" % task.get_id()
      stdout_abbrev = stdout[0:100]
      self._upload_string_to_s3(stdout_key, stdout)
      logging.info("Uploaded stdout for %s to S3" % task.get_id())

    if stderr:
      stderr_key = "%s.stderr" % task.get_id()
      stderr_abbrev = stderr[0:100]
      self._upload_string_to_s3(stderr_key, stderr)
      logging.info("Uploaded stderr for %s to S3" % task.get_id())

    if artifact_archive:
      artifact_archive_key = "%s-artifacts.zip" % task.get_id()
      self._upload_string_to_s3(artifact_archive_key, artifact_archive.getvalue())
      logging.info("Uploaded artifact archive for %s to S3" % task.get_id())

    parms = dict(result_code=result_code,
                 job_id=task.job_id,
                 task_id=task.task_id,
                 attempt=task.attempt,
                 output_archive_hash=output_archive_hash,
                 stdout_key=stdout_key,
                 stdout_abbrev=stdout_abbrev,
                 stderr_key=stderr_key,
                 stderr_abbrev=stderr_abbrev,
                 artifact_archive_key=artifact_archive_key,
                 description=task.description,
                 duration_secs=duration_secs)
    self._execute_query("""
      UPDATE dist_test_tasks SET
        status = %(result_code)s,
        stdout_key = %(stdout_key)s,
        stdout_abbrev = %(stdout_abbrev)s,
        stderr_key = %(stderr_key)s,
        stderr_abbrev = %(stderr_abbrev)s,
        artifact_archive_key = %(artifact_archive_key)s,
        output_archive_hash = %(output_archive_hash)s,
        complete_timestamp = now()
      WHERE job_id = %(job_id)s AND task_id = %(task_id)s AND attempt = %(attempt)s""", parms)

    # Update entry for the description in the dist_test_durations table
    self._execute_query("""
      INSERT INTO dist_test_durations
        VALUES (%(description)s, %(task_id)s, %(duration_secs)s)
      ON DUPLICATE KEY
        UPDATE task_id = %(task_id)s, duration_secs = (duration_secs * 0.7) + (%(duration_secs)s * 0.3)""", parms)

  def generate_output_link(self, key):
    expiry = 60 * 60 * 24 # link should last 1 day
    k = boto.s3.key.Key(self.s3_bucket)
    k.key = key
    return k.generate_url(expiry)

  def fetch_recent_job_rows(self):
    c = self._execute_query("""
        select jobs.job_id,
               min(submit_timestamp) as submit_timestamp,
               count(*) as num_tasks from dist_test_tasks
        join (select distinct (job_id) from dist_test_tasks
              where submit_timestamp > now() - interval 1 day)
        jobs on jobs.job_id = dist_test_tasks.job_id
        group by jobs.job_id
        order by submit_timestamp desc;
    """)
    return c.fetchall()

  def fetch_task(self, job_id, task_id, attempt):
    c = self._execute_query(
      "SELECT * FROM dist_test_tasks WHERE job_id = %(job_id)s AND task_id = %(task_id)s AND attempt = %(attempt)s",
      dict(job_id=job_id, task_id=task_id, attempt=attempt))
    return c.fetchone()

  def fetch_task_rows_for_job(self, job_id):
    c = self._execute_query(
      "SELECT * FROM dist_test_tasks WHERE job_id = %(job_id)s ORDER BY task_id, submit_timestamp",
      dict(job_id=job_id))
    return c.fetchall()

  def fetch_recent_task_durations(self, tasks):
    """For each task, determine the duration of its last completed run.
    This is possibly inaccurate, since it identifies a task purely based
    on its description."""
    if len(tasks) == 0:
      return {}
    # Need to manually construct the values for WHERE IN clause, no support from MySQLdb
    escaped_descs = ["'" + str(MySQLdb.escape_string(task.description)) + "'" for task in tasks]
    where_values = ', '.join(escaped_descs)
    # Fetch duration of last completed run from the dist_test_durations table
    query = """
      SELECT description, duration_secs FROM dist_test_durations
      WHERE description in (%s);
    """ % (where_values)
    c = self._execute_query(query)
    return c.fetchall()

  def _upload_string_to_s3(self, key, data):
    k = boto.s3.key.Key(self.s3_bucket)
    k.key = key
    # The Content-Disposition header sets the filename that the browser
    # will use to download this.
    # We have to cast to str() here, because boto will try to escape the header
    # incorrectly if you pass a unicode string.
    k.set_metadata('Content-Disposition', str('inline; filename=%s' % key))
    k.set_contents_from_string(data, reduced_redundancy=True)

def configure_logger(logger, filename):
  handlers = []
  handlers.append(logging.StreamHandler())
  handlers.append(logging.FileHandler(filename))
  formatter = logging.Formatter("%(asctime)-15s %(levelname)-8s %(message)s")
  for handler in handlers:
    handler.setFormatter(formatter)
    logger.addHandler(handler)
  logger.setLevel(logging.INFO)

