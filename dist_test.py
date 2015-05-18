import beanstalkc
import boto
from ConfigParser import ConfigParser
import logging
import MySQLdb
import os
import uuid
import simplejson
import socket
import threading

class Config(object):
  ACCESS_KEY_CONFIG = ('aws', 'access_key', 'AWS_ACCESS_KEY')
  SECRET_KEY_CONFIG = ('aws', 'secret_key', 'AWS_SECRET_KEY')
  RESULT_BUCKET_CONFIG = ('aws', 'test_result_bucket', 'TEST_RESULT_BUCKET')

  def __init__(self, path=None):
    if path is None:
      path = os.path.join(os.getenv("HOME"), ".dist_test.cnf")
    logging.info("Reading configuration from %s", path)
    self.config = ConfigParser()
    self.config.read(path)

    # Isolate settings
    self.ISOLATE_HOME = self.config.get('isolate', 'home')
    self.ISOLATE_SERVER = self.config.get('isolate', 'server')
    self.ISOLATE_CACHE_DIR = self.config.get('isolate', 'cache_dir')

    # S3 settings
    self.AWS_ACCESS_KEY = self._get_with_env_default(*self.ACCESS_KEY_CONFIG)
    self.AWS_SECRET_KEY = self._get_with_env_default(*self.SECRET_KEY_CONFIG)
    self.AWS_TEST_RESULT_BUCKET = self._get_with_env_default(*self.RESULT_BUCKET_CONFIG)

    # MySQL settings
    self.MYSQL_HOST = self._get_with_env_default('mysql', 'host', 'MYSQL_HOST')
    self.MYSQL_USER = self._get_with_env_default('mysql', 'user', 'MYSQL_USER')
    self.MYSQL_PWD = self._get_with_env_default('mysql', 'password', 'MYSQL_PWD')
    self.MYSQL_DB = self._get_with_env_default('mysql', 'database', 'MYSQL_DB')

    # Beanstalk settings
    self.BEANSTALK_HOST = self._get_with_env_default('beanstalk', 'host', 'BEANSTALK_HOST')

  def _get_with_env_default(self, section, option, env_key):
    if self.config.has_option(section, option):
      return self.config.get(section, option)
    return os.environ.get(env_key)

  def ensure_aws_configured(self):
    self._ensure_configs([self.ACCESS_KEY_CONFIG,
                          self.SECRET_KEY_CONFIG,
                          self.RESULT_BUCKET_CONFIG])

  def _ensure_configs(self, configs):
    for config in configs:
      if self._get_with_env_default(*config) is None:
        raise Exception(("Missing configuration %s.%s. Please set in the config file or " +
                         "set the environment variable %s.") % config)


class Task(object):
  @staticmethod
  def from_json(json):
    return Task(simplejson.loads(json))

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

  def to_json(self):
    job_struct = dict(
      job_id=self.job_id,
      task_id=self.task_id,
      isolate_hash=self.isolate_hash,
      description=self.description,
      timeout=self.timeout)
    return simplejson.dumps(job_struct)

class ReservedTask(object):
  def __init__(self, bs_elem):
    self.bs_elem = bs_elem
    self.task = Task.from_json(bs_elem.body)

class TaskQueue(object):
  def __init__(self, config):
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
    self.thread_local = threading.local()
    logging.info("Connected to MySQL at %s" % config.MYSQL_HOST)
    self._ensure_table()

    self.config.ensure_aws_configured()
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
    return self.thread_local.db

  def _ensure_table(self):
    self._execute_query("""
      CREATE TABLE IF NOT EXISTS dist_test_tasks (
        job_id varchar(100) not null,
        task_id varchar(100) not null,
        description varchar(100) not null,
        submit_timestamp timestamp not null default current_timestamp,
        start_timestamp timestamp,
        hostname varchar(100),
        complete_timestamp timestamp,
        output_archive_hash char(40),
        stdout_abbrev varchar(100),
        stderr_abbrev varchar(100),
        status int,
        PRIMARY KEY(job_id, task_id),
        INDEX(submit_timestamp)
      );""")

  def register_task(self, task):
    self._execute_query("""
      INSERT INTO dist_test_tasks(job_id, task_id, description) VALUES (%s, %s, %s)
    """, [task.job_id, task.task_id, task.description])
  
  def register_tasks(self, tasks):
    tuples = []
    for task in tasks:
      tuples.append((task.job_id, task.task_id, task.description))
    self._execute_query("""
      INSERT INTO dist_test_tasks(job_id, task_id, description) VALUES (%s, %s, %s)
      """, tuples, use_executemany=True)

  def mark_task_running(self, task):
    parms = dict(job_id=task.job_id,
                 task_id=task.task_id,
                 hostname=socket.gethostname())
    self._execute_query("""
      UPDATE dist_test_tasks SET
        start_timestamp=now(),
        hostname=%(hostname)s
      WHERE job_id = %(job_id)s AND task_id = %(task_id)s""", parms)


  def mark_task_finished(self, task, result_code, stdout, stderr, output_archive_hash):
    fn = "%s.stdout" % task.task_id
    self._upload_to_s3(fn, stdout, fn)
    logging.info("Uploaded stdout for %s to S3" % task.task_id)
    fn = "%s.stderr" % task.task_id
    self._upload_to_s3(fn, stderr, fn)
    logging.info("Uploaded stderr for %s to S3" % task.task_id)

    parms = dict(result_code=result_code,
                 job_id=task.job_id,
                 task_id=task.task_id,
                 output_archive_hash=output_archive_hash,
                 stdout_abbrev=stdout[0:100],
                 stderr_abbrev=stderr[0:100])
    logging.info("parms: %s", repr(parms))
    self._execute_query("""
      UPDATE dist_test_tasks SET
        status = %(result_code)s,
        stdout_abbrev = %(stdout_abbrev)s,
        stderr_abbrev = %(stderr_abbrev)s,
        output_archive_hash = %(output_archive_hash)s,
        complete_timestamp = now()
      WHERE task_id = %(task_id)s""", parms)

  def generate_output_link(self, task_row, output):
    expiry = 60 * 60 * 24 # link should last 1 day
    k = boto.s3.key.Key(self.s3_bucket)
    k.key = "%s.%s" % (task_row['task_id'], output)
    return k.generate_url(expiry)

  def fetch_recent_task_rows(self):
    c = self._execute_query("""
      SELECT * FROM dist_test_tasks WHERE
        submit_timestamp > now() - interval 1 hour
      ORDER BY submit_timestamp DESC
      LIMIT 1000""")
    return c.fetchall()

  def fetch_task_rows_for_job(self, job_id):
    c = self._execute_query(
      "SELECT * FROM dist_test_tasks WHERE job_id = %(job_id)s ORDER BY submit_timestamp",
      dict(job_id=job_id))
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
