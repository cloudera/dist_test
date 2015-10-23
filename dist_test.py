import beanstalkc
import boto
from ConfigParser import SafeConfigParser
import errno
import logging
import MySQLdb
import os
import uuid
try:
  import simplejson as json
except:
  import json
import socket
import threading

import config

class Task(object):
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

  def to_json(self):
    job_struct = dict(
      job_id=self.job_id,
      task_id=self.task_id,
      isolate_hash=self.isolate_hash,
      description=self.description,
      timeout=self.timeout,
      attempt=self.attempt,
      max_retries=self.max_retries)
    return json.dumps(job_struct)

class ReservedTask(object):
  def __init__(self, bs_elem):
    self.bs_elem = bs_elem
    self.task = Task.from_json(bs_elem.body)

class TaskQueue(object):
  def __init__(self, config):
    config.ensure_beanstalk_configured()
    self.bs = beanstalkc.Connection(config.BEANSTALK_HOST)

  def submit_task(self, task):
    logging.info("Submitting task %s" % task.job_id)
    self.bs.put(task.to_json())

  def reserve_task(self):
    bs_elem = self.bs.reserve()
    return ReservedTask(bs_elem)

  def stats(self):
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
        start_timestamp timestamp,
        hostname varchar(100),
        complete_timestamp timestamp,
        output_archive_hash char(40),
        stdout_abbrev varchar(100),
        stderr_abbrev varchar(100),
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


  def register_task(self, task):
    self._execute_query("""
      INSERT INTO dist_test_tasks(job_id, task_id, attempt, max_retries, description) VALUES (%s, %s, %s, %s, %s)
    """, [task.job_id, task.task_id, task.attempt, task.max_retries, task.description])

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
    
  def mark_task_finished(self, task, result_code, stdout, stderr, output_archive_hash, duration_secs):
    if stdout:
      fn = "%s.stdout" % task.task_id
      self._upload_to_s3(fn, stdout, fn)
      logging.info("Uploaded stdout for %s to S3" % task.task_id)
    else:
      stdout = ""
    if stderr:
      fn = "%s.stderr" % task.task_id
      self._upload_to_s3(fn, stderr, fn)
      logging.info("Uploaded stderr for %s to S3" % task.task_id)
    else:
      stderr = ""
    parms = dict(result_code=result_code,
                 job_id=task.job_id,
                 task_id=task.task_id,
                 attempt=task.attempt,
                 output_archive_hash=output_archive_hash,
                 stdout_abbrev=stdout[0:100],
                 stderr_abbrev=stderr[0:100],
                 description=task.description,
                 duration_secs=duration_secs)
    self._execute_query("""
      UPDATE dist_test_tasks SET
        status = %(result_code)s,
        stdout_abbrev = %(stdout_abbrev)s,
        stderr_abbrev = %(stderr_abbrev)s,
        output_archive_hash = %(output_archive_hash)s,
        complete_timestamp = now()
      WHERE job_id = %(job_id)s AND task_id = %(task_id)s AND attempt = %(attempt)s""", parms)

    # Update entry for the description in the dist_test_durations table
    self._execute_query("""
      INSERT INTO dist_test_durations
        VALUES (%(description)s, %(task_id)s, %(duration_secs)s)
      ON DUPLICATE KEY
        UPDATE task_id = %(task_id)s, duration_secs = (duration_secs * 0.7) + (%(duration_secs)s * 0.3)""", parms)

  def generate_output_link(self, task_row, output):
    expiry = 60 * 60 * 24 # link should last 1 day
    k = boto.s3.key.Key(self.s3_bucket)
    k.key = "%s.%s" % (task_row['task_id'], output)
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

  def _upload_to_s3(self, key, data, filename):
    k = boto.s3.key.Key(self.s3_bucket)
    k.key = key
    # The Content-Disposition header sets the filename that the browser
    # will use to download this.
    # We have to cast to str() here, because boto will try to escape the header
    # incorrectly if you pass a unicode string.
    k.set_metadata('Content-Disposition', str('inline; filename=%s' % filename))
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

