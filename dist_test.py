import beanstalkc
from ConfigParser import ConfigParser
import logging
import MySQLdb
import os
import uuid
import simplejson


class Config(object):
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
    self.AWS_ACCESS_KEY = self._get_with_env_default('aws', 'access_key', 'AWS_ACCESS_KEY')
    self.AWS_SECRET_KEY = self._get_with_env_default('aws', 'secret_key', 'AWS_SECRET_KEY')

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

class Task(object):
  @staticmethod
  def from_json(json):
    return Task(simplejson.loads(json))

  @staticmethod
  def create(job_id, isolate_hash):
    return Task(dict(job_id=job_id,
                     isolate_hash=isolate_hash,
                     task_id=str(uuid.uuid1())))

  def __init__(self, d):
    self.job_id = d['job_id']
    self.task_id = d['task_id']
    self.isolate_hash = d['isolate_hash']

  def to_json(self):
    job_struct = dict(
      job_id=self.job_id,
      task_id=self.task_id,
      isolate_hash=self.isolate_hash)
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


class ResultsStore(object):
  def __init__(self, config):
    self.db = MySQLdb.connect(config.MYSQL_HOST,
                              config.MYSQL_USER,
                              config.MYSQL_PWD,
                              config.MYSQL_DB)
    logging.info("Connected to MySQL at %s" % config.MYSQL_HOST)
    self._ensure_table()

  def _execute_query(self, query, *args):
    """ Execute a query, automatically reconnecting on disconnection. """
    # We'll try up to 3 times to reconnect
    MAX_ATTEMPTS = 3

    # Error code for the "MySQL server has gone away" error.
    MYSQL_SERVER_GONE_AWAY = 2006

    attempt_num = 0
    while True:
      c = self.db.cursor(MySQLdb.cursors.DictCursor)
      attempt_num = attempt_num + 1
      try:
        c.execute(query, *args)
        return c
      except MySQLdb.OperationalError as err:
        if err.args[0] == MYSQL_SERVER_GONE_AWAY and attempt_num < MAX_ATTEMPTS:
          logging.warn("Forcing reconnect to MySQL: %s" % err)
          self.db = None
          continue
        else:
          raise

  def _ensure_table(self):
    self._execute_query("""
      CREATE TABLE IF NOT EXISTS dist_test_tasks (
        job_id varchar(100) not null,
        task_id varchar(100) not null,
        submit_timestamp timestamp not null default current_timestamp,
        complete_timestamp timestamp,
        stdout_abbrev varchar(100),
        stderr_abbrev varchar(100),
        status int,
        PRIMARY KEY(job_id, task_id),
        INDEX(submit_timestamp)
      );""")

  def register_task(self, task):
    self._execute_query("""
      INSERT INTO dist_test_tasks(job_id, task_id) VALUES (%s, %s)
    """, [task.job_id, task.task_id])

  def mark_task_finished(self, task, result_code, stdout, stderr):
    parms = dict(result_code=result_code,
                 job_id=task.job_id,
                 task_id=task.task_id,
                 stdout_abbrev=stdout[0:100],
                 stderr_abbrev=stderr[0:100])
    logging.info("parms: %s", repr(parms))
    self._execute_query("""
      UPDATE dist_test_tasks SET
        status = %(result_code)s,
        stdout_abbrev = %(stdout_abbrev)s,
        stderr_abbrev = %(stderr_abbrev)s,
        complete_timestamp = now()
      WHERE task_id = %(task_id)s""", parms)

  def fetch_recent_task_rows(self):
    c = self._execute_query("""
      SELECT * FROM dist_test_tasks WHERE
        submit_timestamp > now() - interval 1 hour
      LIMIT 1000""")
    return c.fetchall()

  def fetch_task_rows_for_job(self, job_id):
    c = self._execute_query(
      "SELECT * FROM dist_test_tasks WHERE job_id = %(job_id)s ORDER BY submit_timestamp",
      dict(job_id=job_id))
    return c.fetchall()
