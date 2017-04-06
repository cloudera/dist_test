#!/usr/bin/env python
#
# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.
#
# Simple HTTP server which receives test results from the build slaves and
# stores them in a MySQL database. The test logs are also stored in an S3 bucket.
#

import boto
import cherrypy
import contextlib
import cStringIO
import itertools
import logging
import MySQLdb
import os
import sys
import threading
import time
import uuid
import xml.etree.ElementTree as ET
import zipfile

sys.path = [os.path.realpath(os.path.join(os.path.dirname(os.path.realpath(__file__)), "../grind/python/disttest"))] + sys.path
import parse_test_failure

from config import Config
from cStringIO import StringIO
from jinja2 import Template
from operator import itemgetter

LOG = None

# the test result server, to accumulate success + failed tests, and calculate failure rate.
# TODO: add background thread to delete rows that are too old from DB.
class ResultServer(object):
  def __init__(self, config):
    self.config = config
    self.config.ensure_aws_configured()
    self.config.ensure_mysql_configured()

    self.thread_local = threading.local()
    self._ensure_tables()
    self.s3 = boto.connect_s3(self.config.AWS_ACCESS_KEY, self.config.AWS_SECRET_KEY)
    self.s3_bucket = self.s3.get_bucket(self.config.AWS_TEST_RESULT_BUCKET)
    self.test_dir=self.config.DIST_TEST_TEMP_DIR
    if self.test_dir is None:
      self.test_dir = "/tmp"

  def _connect_mysql(self):
    if hasattr(self.thread_local, "db") and \
          self.thread_local.db is not None:
      return self.thread_local.db

    print "connecting to mysql: %s:%d" %( self.config.MYSQL_HOST, self.config.MYSQL_PORT)
    self.thread_local.db = MySQLdb.connect(
      host=self.config.MYSQL_HOST,
      port=self.config.MYSQL_PORT,
      user=self.config.MYSQL_USER,
      passwd=self.config.MYSQL_PWD,
      db=self.config.MYSQL_DB)
    logging.info("Connected to MySQL at %s:%d" % (self.config.MYSQL_HOST, self.config.MYSQL_PORT))
    self.thread_local.db.autocommit(True)
    return self.thread_local.db

  def _ensure_tables(self):
    self._execute_query("""
      CREATE TABLE IF NOT EXISTS dist_test_results (
        id int not null auto_increment primary key,
        timestamp timestamp not null default current_timestamp,
        job_id varchar(100),
        result_id varchar(150),
        revision varchar(50),
        hostname varchar(255),
        test_name varchar(255),
        status int,
        log_key varchar(256),
        INDEX (job_id),
        INDEX (test_name),
        INDEX (timestamp),
        INDEX (status)
      );""")

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

  def _upload_string_to_s3(self, key, data):
    k = boto.s3.key.Key(self.s3_bucket)
    k.key = key
    # The Content-Disposition header sets the filename that the browser
    # will use to download this.
    # We have to cast to str() here, because boto will try to escape the header
    # incorrectly if you pass a unicode string.
    k.set_metadata('Content-Disposition', str('inline; filename=%s' % key))
    k.set_contents_from_string(data, reduced_redundancy=True)

  def _download_string_from_s3(self, key):
    k = boto.s3.key.Key(self.s3_bucket)
    k.key = key
    encoded_text = None
    archive_buffer = StringIO(k.get_contents_as_string())

    with contextlib.closing(zipfile.ZipFile(archive_buffer, 'r')) as myzip:
      for filename in myzip.namelist():
        try:
          encoded_text = myzip.read(filename)
        except KeyError:
          LOG.error('Did not find %s in zip file' % filename)

    # Ignore errors in decoding, as logs may contain binary data.
    return encoded_text.decode('utf-8', 'ignore')

  def get_root_from_s3key(self, key):
    try:
      log_text = self._download_string_from_s3(key)
      return ET.fromstring(log_text)
    except:
      LOG.error('Failed to get xml root from s3 key(%s)' % key)
      return None

  @cherrypy.expose
  def index(self):
    return "Welcome to the test result server!"

  def populate_database(self, job_id, result_id, revision, hostname, root, artifact_archive_key):
    case_name = []
    if root is None:
      return 'Failure\n'

    if root.tag != 'testsuite':
      return "Failure!\n"
    test_name = root.get('name')
    for case in root.getiterator('testcase'):
      result_code = 0
      error = case.find("error")
      failure = case.find('failure')
      if error is not None:
        result_code |= 1
      if failure is not None:
        result_code |= 2
      # store failed test case names
      case_name.append((case.get('name'), result_code))

    for case, status in case_name:
      parms = dict(job_id=job_id,
                   result_id=result_id,
                   revision=revision,
                   hostname=hostname,
                   test_name=test_name + '#' + case,
                   status=status,
                   log_key=artifact_archive_key)
      logging.info("Handling report: %s" % repr(parms))
      self._execute_query("""
        INSERT INTO dist_test_results(job_id, result_id, revision, hostname, test_name, status, log_key)
        VALUES (%(job_id)s, %(result_id)s, %(revision)s, %(hostname)s, %(test_name)s, %(status)s,
        %(log_key)s)""", parms)
    return "Success!\n"

  def compress_file(self, test_report, id):
    max_size = 200*1024*1024 # 200MB max uncompressed size
    total_size = os.stat(test_report).st_size
    if total_size > max_size:
      # If size exceeds the maximum size, upload a zip with an error message instead
      LOG.info("Task %s generated too many bytes of matched artifacts (%d > %d)," \
               + "uploading archive with error message instead.",
               id, total_size, max_size)
      archive_buffer = cStringIO.StringIO()
      with contextlib.closing(zipfile.ZipFile(archive_buffer, "w")) as myzip:
        myzip.writestr("_ARCHIVE_TOO_BIG_",
                       "Size of matched uncompressed test artifacts exceeded maximum size" \
                       + "(%d bytes > %d bytes)!" % (total_size, max_size))
      return archive_buffer

    # Write out the archive
    archive_buffer = cStringIO.StringIO()
    with contextlib.closing(zipfile.ZipFile(archive_buffer, "w", zipfile.ZIP_DEFLATED)) as myzip:
      arcname = os.path.relpath(test_report, self.test_dir)
      while arcname.startswith("/"):
        arcname = arcname[1:]
      myzip.write(test_report, arcname)

    return archive_buffer

  @cherrypy.expose
  # crawl from the test_task table, and populate result for a given job_id
  def crawl_from_jobid(self, **kwargs):
    # required: job_id, revision, hostname
    args = {}
    args.update(kwargs)
    if 'job_id' not in args:
      return "job_id is required."

    args['revision']=''

    # todo: optimization possible for status=0 jobs
    # keep retrying until all rows in db has artifact_archive_key populated
    all={}
    done={}
    timeout = time.time() + 60
    while True:
      # get all entries with given job_id from dist_test_tasks, then populate results
      c = self._execute_query(
                """SELECT
                     job_id, task_id, attempt,
                     hostname, artifact_archive_key, status
                   FROM dist_test_tasks
                   WHERE job_id = %(jobid)s""",
                dict(jobid=args['job_id']))
      rows = c.fetchall()
      for row in rows:
        uuid = row['job_id'] + row['task_id'] + str(row['attempt'])
        if uuid not in all and uuid not in done:
          all[uuid]=1
        if row['artifact_archive_key'] is not None:
          root = self.get_root_from_s3key(row['artifact_archive_key'])
          ret = self.populate_database(row['job_id'], row['task_id'] + str(row['attempt']), args['revision'],
                               row['hostname'], root, row['artifact_archive_key'])
          LOG.debug('Finished for task %s, result is %s' % (uuid, ret))
          all.pop(uuid, None)
          done[uuid]=1
      if bool(all) is False or time.time() > timeout:
        break
      time.sleep(3)
      LOG.info('Retrying to crawl job %s since %s keys are not populated yet' % (args['job_id'], len(all)))

    return "finished crawling from job", args['job_id']

  @cherrypy.expose
  def add_result(self, **kwargs):
    # required: job_id, revision, hostname
    # required: test_report or key.
    # optional: result_id
    args = {}
    args.update(kwargs)
    if 'job_id' not in args:
      return 'FAILURE: job_id is required!'

    if 'result_id' not in args:
      args['result_id'] = ""

    if 'test_report' in kwargs:
      # We're given a local report file
      test_report = kwargs['test_report']
      f = open(test_report, 'r')
      root = ET.parse(test_report).getroot()
      if root.tag != 'testsuite':
        return "Failure!\n"
      if int(root.get('errors')) != 0 or int(root.get('failures')) != 0:
        # only upload to s3 if test output contains errors
        args['key'] = uuid.uuid1()
        LOG.info('uploading %s to s3 with key %s ' % (test_report, args['key']))
        archive = self.compress_file(test_report, args['job_id'] + args['result_id'])
        self._upload_string_to_s3(args['key'], archive.getvalue())
      else:
        LOG.info('all tests passed in %s, skip uploading' % test_report)
        args['key'] = "success"
    else:
      # We're given an archive that's already uploaded to s3
      root = self.get_root_from_s3key(args['key'])

    return self.populate_database(args['job_id'], args['result_id'], args['revision'], args['hostname'], root, args['key'])

  @cherrypy.expose
  def download_log(self, key):
    expiry = 60 * 60 * 24 # link should last 1 day
    k = boto.s3.key.Key(self.s3_bucket)
    k.key = key
    raise cherrypy.HTTPRedirect(k.generate_url(expiry))

  @cherrypy.expose
  def diagnose(self, key, name):
    log_text = self._download_string_from_s3(key)

    (msg, st, stdout, stderr) = parse_test_failure.extract_failure_summary(log_text, name)
    template = Template("""
      <h1>Error Message</h1>
      <code><pre>{{ msg|e }}</pre></code>
      <h1>Stack Trace</h1>
      <code><pre>{{ st|e }}</pre></code>
      <h1>Standard Output</h1>
      <code><pre>{{ stdout|e }}</pre></code>
      <h1>Standard Error</h1>
      <code><pre>{{ stderr|e }}</pre></code>
    """)
    return self.render_container(template.render(msg=msg, st=st, stdout=stdout, stderr=stderr))

  def recently_failed_html(self):
    """ Return an HTML report of recently failed tests """
    c = self._execute_query(
      "SELECT * from dist_test_results WHERE status != 0 "
      "AND timestamp > NOW() - INTERVAL 1 WEEK "
      "ORDER BY timestamp DESC LIMIT 50")
    failed_tests = c.fetchall()

    prev_date = None
    for t in failed_tests:
      t['is_new_date'] = t['timestamp'].date() != prev_date
      prev_date = t['timestamp'].date()

    template = Template("""
    <h1>50 most recent failures</h1>
    <table class="table">
      <tr>
        <th>test</th>
        <th>exit code</th>
        <th>rev</th>
        <th>machine</th>
        <th>time</th>
      </tr>
      {% for run in failed_tests %}
        {% if run.is_new_date %}
          <tr class="new-date">
            <th colspan="7">{{ run.timestamp.date()|e }}</th>
          </tr>
        {% endif %}
        <tr>
          <td><a href="/test_drilldown?test_name={{ run.test_name |urlencode }}">
              {{ run.test_name |e }}
              </a></td>
          <td>{{ run.status |e }}
            {% if run.log_key %}
              <a href="/download_log?key={{ run.log_key |urlencode }}">download log</a> |
              <a href="/diagnose?key={{ run.log_key |urlencode }}&name={{ run.test_name |urlencode }}">diagnose</a>
            {% endif %}
          </td>
          <td>{{ run.revision |e }}</td>
          <td>{{ run.hostname |e }}</td>
          <td>{{ run.timestamp |e }}</td>
        </tr>
      {% endfor %}
    </table>
    """)
    return template.render(failed_tests=failed_tests)

  def flaky_report_html(self):
    """ Return an HTML report of recently flaky tests """
    c = self._execute_query(
                  """SELECT DISTINCT test_name
                    FROM dist_test_results
                    WHERE timestamp > NOW() - INTERVAL 1 WEEK AND status != 0""")
    names = c.fetchall()

    query_string = """SELECT test_name,
                   DATEDIFF(NOW(), timestamp) AS days_ago,
                   SUM(IF(status != 0, 1, 0)) AS num_failures,
                   COUNT(*) AS num_runs
                 FROM dist_test_results
                 WHERE timestamp > NOW() - INTERVAL 1 WEEK AND test_name in"""\
                   + "('" + "','".join(str(n['test_name']) for n in names) + "')"\
                   + """GROUP BY test_name, days_ago
                   ORDER BY test_name"""
    c = self._execute_query(query_string)
    rows = c.fetchall()

    results = []
    for test_name, test_rows in itertools.groupby(rows, lambda r: r['test_name']):
      # Convert to list so we can consume it multiple times
      test_rows = list(test_rows)

      # Compute summary for last 7 days and last 2 days
      runs_7day = sum(r['num_runs'] for r in test_rows)
      failures_7day = sum(r['num_failures'] for r in test_rows)
      runs_2day = sum(r['num_runs'] for r in test_rows if r['days_ago'] < 2)
      failures_2day = sum(r['num_failures'] for r in test_rows if r['days_ago'] < 2)

      # Compute a sparkline (percentage failure for each day)
      sparkline = [0 for x in xrange(8)]
      for r in test_rows:
        if r['num_runs'] > 0:
          percent = float(r['num_failures']) / r['num_runs'] * 100
        else:
          percent = 0
        sparkline[7 - r['days_ago']] = percent

      # Add to results list for tablet.
      results.append(dict(test_name=test_name,
                          runs_7day=runs_7day,
                          failures_7day=failures_7day,
                          runs_2day=runs_2day,
                          failures_2day=failures_2day,
                          sparkline=",".join("%.2f" % p for p in sparkline)))

      results = sorted(results, key=itemgetter('failures_7day'), reverse=True)
    return Template("""
    <h1>Flaky rate over last week</h1>
    <table class="table" id="flaky-rate">
      <tr>
       <th>test</th>
       <th>failure rate (7-day)</th>
       <th>failure rate (2-day)</th>
       <th>trend</th>
      </tr>
      {% for r in results %}
      <tr>
        <td><a href="/test_drilldown?test_name={{ r.test_name |urlencode }}">
              {{ r.test_name |e }}
            </a></td>
        <td>{{ r.failures_7day |e }} / {{ r.runs_7day }}
            ({{ "%.2f"|format(r.failures_7day / r.runs_7day * 100) }}%)
        </td>
        <td>{{ r.failures_2day |e }} / {{ r.runs_2day }}
            {% if r.runs_2day > 0 %}
            ({{ "%.2f"|format(r.failures_2day / r.runs_2day * 100) }}%)
            {% endif %}
        </td>
        <td><span class="inlinesparkline">{{ r.sparkline |e }}</span></td>
      </tr>
      {% endfor %}
    </table>
    <script type="text/javascript">
      $(function() {
        $('.inlinesparkline').sparkline('html', {
           'height': 25,
            'width': '40px',
            'chartRangeMin': 0,
            'tooltipFormatter': function(sparkline, options, fields) {
              return String(7 - fields.x) + "d ago: " + fields.y + "%"; }
        });
      });
    </script>
    """).render(results=results)

  @cherrypy.expose
  def list_failed_tests(self, build_pattern, num_days):
    num_days = int(num_days)
    c = self._execute_query(
              """SELECT DISTINCT
                   test_name
                 FROM dist_test_results
                 WHERE timestamp > NOW() - INTERVAL %(num_days)s DAY
                   AND status != 0
                   AND build_id LIKE %(build_pattern)s""",
              dict(build_pattern=build_pattern,
                   num_days=num_days))
    cherrypy.response.headers['Content-Type'] = 'text/plain'
    return "\n".join(row['test_name'] for row in c.fetchall())

  @cherrypy.expose
  def test_drilldown(self, test_name):
    # Get summary statistics for the test, grouped by revision
    c = self._execute_query(
              """SELECT
                   revision,
                   MIN(timestamp) AS first_run,
                   SUM(IF(status != 0, 1, 0)) AS num_failures,
                   COUNT(*) AS num_runs
                 FROM dist_test_results
                 WHERE timestamp > NOW() - INTERVAL 1 WEEK
                   AND test_name = %(test_name)s
                 GROUP BY revision
                 ORDER BY first_run DESC""",
              dict(test_name=test_name))
    revision_rows = c.fetchall()

    # Convert to a dictionary, by revision
    rev_dict = dict( [(r['revision'], r) for r in revision_rows] )

    # Add an empty 'runs' array to each revision to be filled in below
    for r in revision_rows:
      r['runs'] = []

    # Append the specific info on failures
    c.execute("SELECT * from dist_test_results "
              "WHERE timestamp > NOW() - INTERVAL 1 WEEK "
              "AND test_name = %(test_name)s "
              "AND status != 0",
              dict(test_name=test_name))
    for failure in c.fetchall():
      rev_dict[failure['revision']]['runs'].append(failure)

    return self.render_container(Template("""
    <h1>{{ test_name |e }} flakiness over recent revisions</h1>
    <a href="/">Back to home</a>
    {% for r in revision_rows %}
      <h4>{{ r.revision }} (Failed {{ r.num_failures }} / {{ r.num_runs }})</h4>
      {% if r.num_failures > 0 %}
        <table class="table">
          <tr>
            <th>time</th>
            <th>failed test</th>
            <th>exit code</th>
            <th>machine</th>
            <th>build</th>
          </tr>
          {% for run in r.runs %}
            <tr {% if run.status != 0 %}
                  style="background-color: #faa;"
                {% else %}
                  style="background-color: #afa;"
                {% endif %}>
              <td>{{ run.timestamp |e }}</td>
              <td>{{ run.test_name |e }}
              </td>
              <td>{{ run.status |e }}
                {% if run.log_key %}
                  <a href="/download_log?key={{ run.log_key |urlencode }}">download log</a> |
                  <a href="/diagnose?key={{ run.log_key |urlencode }}&name={{ run.test_name |urlencode }}">diagnose</a>
                {% endif %}
              </td>
              <td>{{ run.hostname |e }}</td>
              <td>{{ run.build_id |e }}</td>
            </tr>
          {% endfor %}
        </table>
      {% endif %}
    {% endfor %}
    """).render(revision_rows=revision_rows, test_name=test_name))

  @cherrypy.expose
  def index(self):
    body = self.flaky_report_html()
    body += "<hr/>"
    body += self.recently_failed_html()
    return self.render_container(body)

  def render_container(self, body):
    """ Render the "body" HTML inside of a bootstrap container page. """
    template = Template("""
    <!DOCTYPE html>
    <html>
      <head><title>Test results dashboard</title>
      <link rel="stylesheet" href="//maxcdn.bootstrapcdn.com/bootstrap/3.2.0/css/bootstrap.min.css" />
      <style>
        .new-date { border-bottom: 2px solid #666; }
        #flaky-rate tr :nth-child(1) { width: 70%; }

        /* make sparkline data not show up before loading */
        .inlinesparkline { color: #fff; }
        /* fix sparkline tooltips */
        .jqstooltip {
          -webkit-box-sizing: content-box;
          -moz-box-sizing: content-box;
          box-sizing: content-box;
        }
      </style>
    </head>
    <body>
      <script src="//ajax.googleapis.com/ajax/libs/jquery/1.11.1/jquery.min.js"></script>
      <script src="//maxcdn.bootstrapcdn.com/bootstrap/3.2.0/js/bootstrap.min.js"></script>
      <script src="https://cdnjs.cloudflare.com/ajax/libs/jquery-sparklines/2.1.2/jquery.sparkline.min.js"></script>
      <div class="container-fluid">
      {{ body }}
      </div>
    </body>
    </html>
    """)
    return template.render(body=body)

if __name__ == "__main__":
  config = Config()
  logging.basicConfig(level=logging.INFO)
  LOG = logging.getLogger('dist_test.test_result_server')
  cherrypy.config.update(
    {'server.socket_host': '0.0.0.0',
     'response.timeout': 1800} )
  LOG.info("Starting test result server")
  cherrypy.quickstart(ResultServer(config))
