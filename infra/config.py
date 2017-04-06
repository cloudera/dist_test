from ConfigParser import SafeConfigParser
import errno
import logging
import os
import urllib2

class Config(object):
  # S3 settings
  AWS_ACCESS_KEY_CONFIG = ('aws', 'access_key', 'AWS_ACCESS_KEY')
  AWS_SECRET_KEY_CONFIG = ('aws', 'secret_key', 'AWS_SECRET_KEY')
  AWS_TEST_RESULT_BUCKET_CONFIG = ('aws', 'test_result_bucket', 'TEST_RESULT_BUCKET')

  # MySQL settings
  MYSQL_HOST_CONFIG = ('mysql', 'host', 'MYSQL_HOST')
  MYSQL_PORT_CONFIG = ('mysql', 'port', 'MYSQL_PORT')
  MYSQL_USER_CONFIG = ('mysql', 'user', 'MYSQL_USER')
  MYSQL_PWD_CONFIG = ('mysql', 'password', 'MYSQL_PWD')
  MYSQL_DB_CONFIG = ('mysql', 'database', 'MYSQL_DB')

  # Isolate settings
  ISOLATE_HOME_CONFIG = ('isolate', 'home', "ISOLATE_HOME")
  ISOLATE_SERVER_CONFIG = ('isolate', 'server', "ISOLATE_SERVER")
  ISOLATE_CACHE_DIR_CONFIG = ('isolate', 'cache_dir', "ISOLATE_CACHE_DIR")

  # Beanstalk settings
  BEANSTALK_HOST_CONFIG = ('beanstalk', 'host', 'BEANSTALK_HOST')

  # Dist test settings
  DIST_TEST_MASTER_CONFIG = ('dist_test', 'master', "DIST_TEST_MASTER")
  DIST_TEST_JOB_PATH_CONFIG = ('dist_test', 'job_path', 'DIST_TEST_JOB_PATH')
  DIST_TEST_USER_CONFIG = ('dist_test', 'user', 'DIST_TEST_USER')
  DIST_TEST_PASSWORD_CONFIG = ('dist_test', 'password', 'DIST_TEST_PASSWORD')
  DIST_TEST_RESULT_SERVER_CONFIG = ('dist_test', 'result_server', 'DIST_TEST_RESULT_SERVER')
  DIST_TEST_TEMP_DIR_CONFIG = ('dist_test', 'temp_dir', 'DIST_TEST_TEMP_DIR')

  def __init__(self, path=None):
    if path is None:
      path = os.getenv("DIST_TEST_CNF")
    if path is None:
      path = os.path.join(os.getenv("HOME"), ".dist_test.cnf")
    logging.info("Reading configuration from %s", path)
    # Populate parser with default values
    defaults = {
      "log_dir" : os.path.join(os.path.dirname(os.path.realpath(__file__)), "logs"),
      "submit_gce_metrics" : "True",
      "allowed_ip_ranges": "0.0.0.0/0",
      "accounts": "{}",
    }
    self.config = SafeConfigParser(defaults)
    self.config.read(path)

    # Isolate settings
    self.ISOLATE_HOME = self._get_with_env_override(*self.ISOLATE_HOME_CONFIG)
    self.ISOLATE_SERVER = self._get_with_env_override(*self.ISOLATE_SERVER_CONFIG)
    self.ISOLATE_CACHE_DIR = self._get_with_env_override(*self.ISOLATE_CACHE_DIR_CONFIG)

    # S3 settings
    self.AWS_ACCESS_KEY = self._get_with_env_override(*self.AWS_ACCESS_KEY_CONFIG)
    self.AWS_SECRET_KEY = self._get_with_env_override(*self.AWS_SECRET_KEY_CONFIG)
    self.AWS_TEST_RESULT_BUCKET = self._get_with_env_override(*self.AWS_TEST_RESULT_BUCKET_CONFIG)

    # MySQL settings
    self.MYSQL_HOST = self._get_with_env_override(*self.MYSQL_HOST_CONFIG)
    try:
      self.MYSQL_PORT = int(self._get_with_env_override(*self.MYSQL_PORT_CONFIG))
    except:
      self.MYSQL_PORT = 3306
    self.MYSQL_USER = self._get_with_env_override(*self.MYSQL_USER_CONFIG)
    self.MYSQL_PWD = self._get_with_env_override(*self.MYSQL_PWD_CONFIG)
    self.MYSQL_DB = self._get_with_env_override(*self.MYSQL_DB_CONFIG)

    # Beanstalk settings
    self.BEANSTALK_HOST = self._get_with_env_override(*self.BEANSTALK_HOST_CONFIG)

    # dist_test settings
    if not self.config.has_section('dist_test'):
      self.config.add_section('dist_test')
    self.DIST_TEST_MASTER = self._get_with_env_override(*self.DIST_TEST_MASTER_CONFIG)
    self.DIST_TEST_JOB_PATH = self._get_with_env_override(*self.DIST_TEST_JOB_PATH_CONFIG)
    if self.DIST_TEST_JOB_PATH is None:
      self.DIST_TEST_JOB_PATH = os.path.expanduser("~/.dist-test-last-job")
    self.DIST_TEST_USER = self._get_with_env_override(*self.DIST_TEST_USER_CONFIG)
    self.DIST_TEST_PASSWORD = self._get_with_env_override(*self.DIST_TEST_PASSWORD_CONFIG)

    # dist_test master configs (in the 'dist_test' section)
    self.DIST_TEST_ALLOWED_IP_RANGES = self.config.get('dist_test', 'allowed_ip_ranges')
    self.ACCOUNTS = self.config.get('dist_test', 'accounts')

    self.log_dir = self.config.get('dist_test', 'log_dir')
    # Make the log directory if it doesn't exist
    Config.mkdir_p(self.log_dir)
    # dist_test result server settings
    self.DIST_TEST_RESULT_SERVER = self._get_with_env_override(*self.DIST_TEST_RESULT_SERVER_CONFIG)
    self.DIST_TEST_TEMP_DIR = self._get_with_env_override(*self.DIST_TEST_TEMP_DIR_CONFIG)

    self.SERVER_ACCESS_LOG = os.path.join(self.log_dir, "server-access.log")
    self.SERVER_ERROR_LOG = os.path.join(self.log_dir, "server-error.log")
    self.SERVER_LOG = os.path.join(self.log_dir, "server.log")
    self.SLAVE_LOG = os.path.join(self.log_dir, "slave.log")

  @staticmethod
  def mkdir_p(path):
    """Similar to mkdir -p, make a directory ignoring EEXIST"""
    try:
      os.makedirs(path)
    except OSError as exc:
      if exc.errno == errno.EEXIST and os.path.isdir(path):
        pass
      else:
        raise

  def _get_with_env_override(self, section, option, env_key):
    env_value = os.environ.get(env_key)
    if env_value is not None:
      return env_value
    file_value = None
    if self.config.has_option(section, option):
      file_value = self.config.get(section, option)
    return file_value

  def ensure_aws_configured(self):
    self._ensure_configs([self.AWS_ACCESS_KEY_CONFIG,
                          self.AWS_SECRET_KEY_CONFIG,
                          self.AWS_TEST_RESULT_BUCKET_CONFIG])

  def ensure_isolate_configured(self):
    self._ensure_configs([self.ISOLATE_HOME_CONFIG,
                          self.ISOLATE_SERVER_CONFIG,
                          self.ISOLATE_CACHE_DIR_CONFIG])

  def ensure_mysql_configured(self):
    self._ensure_configs([self.MYSQL_HOST_CONFIG,
                          self.MYSQL_USER_CONFIG,
                          self.MYSQL_PWD_CONFIG,
                          self.MYSQL_DB_CONFIG])

  def ensure_beanstalk_configured(self):
    self._ensure_configs([self.BEANSTALK_HOST_CONFIG])

  def ensure_dist_test_configured(self):
    self._ensure_configs([self.DIST_TEST_MASTER_CONFIG])

  def ensure_result_server_configured(self):
    self._ensure_configs([self.DIST_TEST_RESULT_SERVER_CONFIG])

  def _ensure_configs(self, configs):
    for config in configs:
      if self._get_with_env_override(*config) is None:
        raise Exception(("Missing configuration %s.%s. Please set in the config file or " +
                         "set the environment variable %s.") % config)

  def configure_auth(self):
    """
    Configure urllib2 to pass authentication information if provided
    in the configuration.
    """
    if not self.DIST_TEST_USER:
      return
    password_mgr = urllib2.HTTPPasswordMgrWithDefaultRealm()
    password_mgr.add_password(None, self.DIST_TEST_MASTER,
        self.DIST_TEST_USER, self.DIST_TEST_PASSWORD)
    handler = urllib2.HTTPDigestAuthHandler(password_mgr)
    opener = urllib2.build_opener(handler)
    urllib2.install_opener(opener)
