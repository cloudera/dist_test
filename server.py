#!/usr/bin/env python

import base64
import cgi
import cherrypy
import datetime
import logging
import os
from jinja2 import Template
import urllib
try:
  import simplejson as json
except:
  import json
import StringIO
import gzip
from collections import defaultdict

from config import Config
import dist_test

TRACE_HTML = os.path.join(os.path.dirname(__file__), "trace.html")

LOG = None

class DistTestServer(object):

  global LOG

  def __init__(self, config):
    self.config = config
    self.task_queue = dist_test.TaskQueue(self.config)
    self.results_store = dist_test.ResultsStore(self.config)

  @cherrypy.expose
  def index(self):
    stats = self.task_queue.stats()
    body = "<h1>Stats</h1>\n" + self._render_stats(stats)
    recent_jobs = self.results_store.fetch_recent_job_rows()
    body += self._render_jobs(recent_jobs)
    return self.render_container(body)

  @cherrypy.expose
  def job(self, job_id, task_id=None):
    tasks = self.results_store.fetch_task_rows_for_job(job_id)
    if len(tasks) == 0:
      return "No tasks found for specified job_id %s" % job_id
    job_summary, task_groups = self._summarize_tasks(tasks)
    body = ""
    body += self._render_job_header(job_id, job_summary, task_groups)
    body += self._render_tasks(tasks, job_summary, task_groups)
    return self.render_container(body)

  @staticmethod
  def _delta_us(delta):
    return delta.seconds * 1000000 + delta.microseconds

  @cherrypy.expose
  def trace(self, job_id):
    tasks = self.results_store.fetch_task_rows_for_job(job_id)
    ret = []
    min_st = min(task['submit_timestamp'] for task in tasks)
    for task in tasks:
      if task['complete_timestamp']:
        ret.append(dict(cat="run", pid=task['hostname'], ph="X",
                        name=task['description'],
                        dur=self._delta_us(task['complete_timestamp'] - task['start_timestamp']),
                        ts=self._delta_us(task['start_timestamp'] - min_st)))
    trace_gz = StringIO.StringIO()
    json.dump({"traceEvents": ret},
                    gzip.GzipFile(fileobj=trace_gz, mode="w"))
    trace_gz_b64 = base64.encodestring(trace_gz.getvalue())
    with open(TRACE_HTML, "r") as f:
      trace = f.read()
      trace = trace.replace("SUBSTITUTE_TRACE_HERE", trace_gz_b64)
    return trace

  @cherrypy.expose
  def view_log(self, job_id, task_id, attempt, log):
    task = self.results_store.fetch_task(job_id, task_id, attempt)
    if task is None:
      return "Could not find requested task"

    if log == "stderr":
      key = task['stderr_key']
    elif log == "stdout":
      key = task['stdout_key']
    else:
      return "Unknown log type"

    url = self.results_store.generate_output_link(key)
    return cgi.escape(urllib.urlopen(url).read(), quote=True)

  @cherrypy.expose
  @cherrypy.tools.json_out()
  def cancel_job(self, job_id):
    self.results_store.cancel_job(job_id)
    return {"status": "SUCCESS"}

  @cherrypy.expose
  @cherrypy.tools.json_out()
  def submit_job(self, job_id, job_json):
    job_desc = json.loads(job_json)

    tasks = []
    for i, task_desc in enumerate(job_desc['tasks']):
      task_desc['job_id'] = job_id
      task_desc['task_id'] = "%s.%d" % (task_desc['isolate_hash'], i)
      task = dist_test.Task(task_desc)
      tasks.append(task)

    tasks = self._sort_tasks_by_duration(tasks)

    self.results_store.register_tasks(tasks)
    for task in tasks:
      self.task_queue.submit_task(task)
    return {"status": "SUCCESS"}

  @cherrypy.expose
  @cherrypy.tools.json_out()
  def retry_task(self, task_json):
    task = dist_test.Task.from_json(task_json)
    if task.attempt < task.max_retries:
      task.attempt += 1
      self.results_store.register_tasks([task])
      # Run retry tasks with a boosted priority. This prevents them from straggling
      # if we've already started running another job.
      self.task_queue.submit_task(task, priority=1000)
    return {"status": "SUCCESS"}

  def _sort_tasks_by_duration(self, tasks):
    """Sort the tasks by the duration of their last completed execution, descending.

    This is a simple form of longest-task-first scheduling to reduce the
    effect of stragglers on overall job runtime."""
    task_durations = self.results_store.fetch_recent_task_durations(tasks)
    # turn it into a lookup table of description -> duration
    dur_by_desc = defaultdict(int)
    for t in task_durations:
      dur_by_desc[t["description"]] = int(t["duration_secs"])
    tasks_with_duration = []
    for t in tasks:
      # Tuple of (task, duration)
      tasks_with_duration.append((t, dur_by_desc[t.description]))
    # Sort tasks descending based on duration
    sorted_tasks = sorted(tasks_with_duration, key=lambda t: t[1], reverse=True)
    # Trim off the durations
    sorted_tasks = [x[0] for x in sorted_tasks]
    return sorted_tasks

  @cherrypy.expose
  @cherrypy.tools.json_out()
  def job_status(self, job_id):
    tasks = self.results_store.fetch_task_rows_for_job(job_id)
    job_summary, task_groups = self._summarize_tasks(tasks, json_compatible=True)
    return job_summary

  @cherrypy.expose
  @cherrypy.tools.json_out()
  def failed_tasks(self, job_id):
    # Deprecated, use the "tasks" endpoint instead.
    return self.tasks(job_id, status="failed")

  @cherrypy.expose
  @cherrypy.tools.json_out()
  def tasks(self, job_id, status=None):
    if status not in (None, "failed", "succeeded", "finished"):
      return "Unknown status type"
    # fetch all tasks and filter by status. By default (None) return all tasks.
    tasks = self.results_store.fetch_task_rows_for_job(job_id)
    filtered = tasks
    if status == "failed":
      filtered = [t for t in tasks if t['status'] is not None and t['status'] != 0]
    elif status == "succeeded":
      filtered = [t for t in tasks if t['status'] is not None and t['status'] == 0]
    elif status == "finished":
      filtered = [t for t in tasks if t['status'] is not None]
    # construct a record for each filtered task
    records = []
    for t in filtered:
      record = dict(task_id=t['task_id'],
                    description=t['description'])
      if t['stdout_key']:
        record['stdout_link'] = self.results_store.generate_output_link(t['stdout_key'])
      if t['stderr_key']:
        record['stderr_link'] = self.results_store.generate_output_link(t['stderr_key'])
      if t['artifact_archive_key']:
        record['artifact_archive_link'] = self.results_store.generate_output_link(t['artifact_archive_key'])
      records.append(record)
    return records

  def _summarize_tasks(self, tasks, json_compatible=False):
    """Computes aggregate statistics on a set of tasks and groups tasks into groups based on task_id.
    Returns a tuple of (statistics, task_groups).

    The json_compatible kwarg is used to request JSON-compatible output, which is used by the client
    to report progress.

    The statistics object is a dictionary of string keys to integer values.

    task_groups is a dictionary that maps a string task_id to the list of tasks with that task_id.
    This is used to group together multiple attempted runs when a task is configured to
    be retried on failure.
    Tasks are uniquely identified by the compound key (job_id, task_id, attempt).
    """

    result = {}
    result['total_tasks'] = len(tasks)
    result['finished_tasks'] = len([1 for t in tasks if t['status'] is not None])
    result['running_tasks'] = len([1 for t in tasks if t['status'] is None])
    result['retried_tasks'] = len([1 for t in tasks if t['attempt'] > 0])
    result['timedout_tasks'] = len([1 for t in tasks if t['status'] == -9])
    # Calculating success and failure requires grouping by task_id,
    # since flaky tasks can be automatically retried
    task_groups = defaultdict(list)
    result['failed_groups'] = 0
    result['succeeded_groups'] = 0
    result['flaky_groups'] = 0
    for t in tasks:
      task_groups[t['task_id']].append(t)
    result['total_groups'] = len(task_groups)
    for group in task_groups.values():
      failed_tasks = [t['status'] is not None and t['status'] != 0 for t in group]
      failed = all(failed_tasks)
      succeeded = any([t['status'] == 0 for t in group])
      timedout = all([t['status'] == -9 for t in group])
      if failed:
        result['failed_groups'] += 1
      if succeeded:
        result['succeeded_groups'] += 1
      if timedout:
        result['timedout_tasks'] += 1
      # If we succeeded after some failures, increment flaky count
      if succeeded and any(failed_tasks):
        result['flaky_groups'] += 1
    result['finished_groups'] = result['failed_groups'] + result['succeeded_groups']

    # Determine job state: if it's finished, how long its been running
    finish_time = None
    runtime = None
    submit_time = min([t["submit_timestamp"] for t in tasks])

    result['status'] = "running"
    stop = datetime.datetime.now()

    if result['total_tasks'] == result['finished_tasks']:
      result['status'] = "finished"
      finish_time = max([t["complete_timestamp"] for t in tasks])
      stop = finish_time
    runtime = stop - submit_time

    # datetimes can't be auto-JSON'd, do not include them
    if not json_compatible:
      result["submit_time"] = submit_time
      result["finish_time"] = finish_time
      result['runtime'] = runtime

    return result, task_groups

  def _render_stats(self, stats):
    template = Template("""
      <code>
        Queue length: {{ stats['current-jobs-ready'] }}
        Running: {{ stats['current-jobs-reserved'] }}
        Idle slaves: {{ stats['current-waiting'] }}
      </code>""")
    return template.render(stats=stats)


  def _render_jobs(self, jobs):
    stats = {}
    stats["total_jobs"] = len(jobs)
    stats["total_tasks"] = sum([j["num_tasks"] for j in jobs])

    template = Template("""
    <h1>Recent Jobs (last 1 day)</h1>
    <br style="clear: both;"/>
    <table class="table" id="jobs">
    <thead>
      <tr>
        <th>Job ({{ stats.total_jobs |e }}) </th>
        <th>Submitted</th>
        <th>Num Tasks ({{ stats.total_tasks |e }})</th>
      </tr>
    </thead>
    <tbody>
      {% for job in jobs %}
        <tr>
          <td><a href="/job?job_id={{ job.job_id |urlencode }}">{{ job.job_id |e }}</a></td>
          <td>{{ job.submit_timestamp |e }}</td>
          <td>{{ job.num_tasks |e }}</td>
        </tr>
      {% endfor %}
      </tbody>
    </table>
    """)
    return template.render(jobs=jobs, stats=stats)

  def _render_job_header(self, job_id, job_summary, task_groups):
    if job_summary['total_groups'] > 0:
      success_percent = job_summary['succeeded_groups'] * 100 / float(job_summary['total_groups'])
      fail_percent = job_summary['failed_groups'] * 100 / float(job_summary['total_groups'])
    else:
      success_percent = 0
      fail_percent = 0

    job = {}
    job["success_percent"] = "%.2f%%" % success_percent
    job["fail_percent"] = "%.2f%%" % fail_percent
    job["job_id"] = job_id

    print job
    template = Template("""
    <h1> Job {{ job.job_id | e }} ({{ job_summary.status }}) </h1>
    <div class="progress-bar">
      <div class="filler green" style="width: {{ job.success_percent }};"></div>
      <div class="filler red" style="width: {{ job.fail_percent }};"></div>
    </div>

    <br style="clear:both"/>
    <p>
    <strong>Submitted: {{ job_summary.submit_time }}</strong>
    </p>
    <p>
    <strong>Runtime: {{ job_summary.runtime }}</strong>
    </p>
    <p>
    <a href="/">Back to home</a>
    <a href="/trace?job_id={{ job.job_id | urlencode }}">Trace view</a>
    </p>

    """)
    return template.render(job=job, job_summary=job_summary)

  def _generate_view_link(self, task, output):
    return "/view_log?job_id=%s&task_id=%s&attempt=%s&log=%s" % \
        (urllib.quote(task["job_id"]), urllib.quote(task["task_id"]), urllib.quote(str(task["attempt"])), urllib.quote(output))


  def _render_tasks(self, tasks, job_summary, task_groups):
    # Calculate status of each task group
    task_to_group_status = defaultdict(dict)
    for task_id, group in task_groups.iteritems():
      # Success if any of the tasks in group succeeded
      task_to_group_status[task_id]['succeeded'] = any([t['status'] == 0 for t in group])
      # Failed if we hit the max retry and it failed
      task_to_group_status[task_id]['failed'] = any([t['status'] is not None and t['status'] != 0 for t in group if t['attempt'] == t['max_retries']])

    for t in tasks:
      # stdout/stderr links
      if t['stdout_key']:
        t['stdout_link'] = self.results_store.generate_output_link(t['stdout_key'])
        t['stdout_view_link'] = self._generate_view_link(t, "stdout")
      if t['stderr_key']:
        t['stderr_link'] = self.results_store.generate_output_link(t['stderr_key'])
        t['stderr_view_link'] = self._generate_view_link(t, "stderr")
      # artifact link
      if t['artifact_archive_key']:
        t['artifact_archive_link'] = self.results_store.generate_output_link(t['artifact_archive_key'])
      # Calculate the elapsed time
      if t['start_timestamp'] is not None and t['complete_timestamp'] is not None:
        delta = t['complete_timestamp'] - t['start_timestamp']
        t['runtime'] = delta.seconds + (delta.days*24*60*60)
      elif t['start_timestamp'] is not None:
        delta = datetime.datetime.now() - t['start_timestamp']
        t['runtime'] = delta.seconds + (delta.days*24*60*60)
      else:
        t['runtime'] = None
      # Task status.
      #   All failures, no retries left: mark failures as failed
      #   All failures, some retries left: mark failures as flaky
      #   One success: mark failures as flaky
      status = []
      if t['status'] is None:
        status = ['task-running']
      elif t['status'] == 0:
        status = ['task-successful']
      else:
        status = ['task-failed']
        group_status = task_to_group_status[t['task_id']]
        if group_status['succeeded'] or not group_status['failed']:
          status = ['task-flaky']
      t['status_class'] = ' '.join(status)

    template = Template("""
    <br style="clear: both;"/>
    <div>
      Show:
      <a id="show-all">all ({{ job_summary.total_groups }})</a> |
      <a id="show-running">running ({{ job_summary.running_tasks }})</a> |
      <a id="show-failed">failed ({{ job_summary.failed_groups }})</a> |
      <a id="show-successful">successful ({{ job_summary.succeeded_groups }})</a> |
      <a id="show-timedout">timed out ({{ job_summary.timedout_tasks }})</a> |
      <a id="show-flaky">flaky ({{ job_summary.flaky_groups }})</a>
    </div>
    <table class="table sortable" id="tasks">
    <thead>
      <tr>
        <th>time(s)</th>
        <th>description</th>
        <th>hostname</th>
        <th>status</th>
        <th>results</th>
        <th>stdout</th>
        <th>stderr</th>
        <th>artifacts</th>
        <th>task</th>
        <th>attempt</th>
      </tr>
    </thead>
    <tbody>
      {% for task in tasks %}
        <tr class="{{ task.status_class |e }}">
          <td>{{ task.runtime | int |e }}</td>
          <td>{{ task.description |e }}</td>
          <td>{{ task.hostname |e }}</td>
          <td>{{ task.status |e }}</td>
          <td>{{ task.output_archive_hash |e }}</td>
          <td>{{ task.stdout_abbrev |e }}
              {% if task.stdout_link %}
              <br/>
              <a class="view" href="#" viewlink="{{ task.stdout_view_link |e }}" viewheader="{{ task.description |e }}.{{ task.task_id |e }}.stdout">view</a>
              <a href="{{ task.stdout_link |e }}">download</a>
              {% endif %}
          </td>
          <td>{{ task.stderr_abbrev |e }}
              {% if task.stderr_link %}
              <br/>
              <a class="view" href="#" viewlink="{{ task.stderr_view_link |e }}" viewheader="{{ task.description |e }}.{{ task.task_id |e }}.stderr">view</a>
              <a href="{{ task.stderr_link |e }}">download</a>
              {% endif %}
          </td>
          <td>
              {% if task.artifact_archive_link %}
              <a href="{{ task.artifact_archive_link |e }}">download</a>
              {% endif %}
          </td>
          <td>{{ task.task_id |e }}</td>
          <td>{{ task.attempt |e }}</td>
        </tr>
      {% endfor %}
      </tbody>
    </table>
    """)
    return template.render(tasks=tasks, job_summary=job_summary)

  def render_container(self, body):
    """ Render the "body" HTML inside of a bootstrap container page. """
    template = Template("""
    <!DOCTYPE html>
    <html>
      <head><title>Distributed Test Server</title>
      <link rel="stylesheet" href="//maxcdn.bootstrapcdn.com/bootstrap/3.2.0/css/bootstrap.min.css" />
      <style>
        .progress-bar {
          border: 1px solid #666;
          background: #eee;
          height: 30px;
          width: 80%;
          margin: auto;
          padding: 0;
          margin-bottom: 1em;
        }
        .progress-bar .filler {
          margin: 0px;
          height: 100%;
          border: 0;
          float:left;
        }
        .filler.green { background-color: #0f0; }
        .task-running { background-color: #ffa; }
        .task-successful { background-color: #afa; }
        .task-failed { background-color: #faa; }
        .task-flaky { background-color: #fc9; }
        .filler.red { background-color: #f00; }

        /* Required for scrollbar on modal window */
        .modal-dialog { overflow-y: initial !important; }
        .modal-body {
          height: 100%;
          overflow-y: auto;
          font-family: monospace;
          white-space:pre;
        }

      </style>
    </head>
    <body>

      <!-- Modal -->
      <div id="logModal" class="modal fade" role="dialog">
        <div class="modal-dialog modal-lg">

          <!-- Modal content-->
          <div class="modal-content">
            <div class="modal-header">
              <button type="button" class="close" data-dismiss="modal">&times;</button>
              <h4 class="modal-title">Modal Header</h4>
            </div>
            <div class="modal-body">
              <p>Some text in the modal.</p>
            </div>
            <div class="modal-footer">
              <button type="button" class="btn btn-default" data-dismiss="modal">Close</button>
            </div>
          </div>

        </div>
      </div>
      <div class="container-fluid">
      {{ body }}
      </div>
      <script src="//ajax.googleapis.com/ajax/libs/jquery/1.11.1/jquery.min.js"></script>
      <script src="//maxcdn.bootstrapcdn.com/bootstrap/3.2.0/js/bootstrap.min.js"></script>
      <script src="//cdnjs.cloudflare.com/ajax/libs/jquery.tablesorter/2.18.2/js/jquery.tablesorter.min.js"></script>
      <script>
        $(document).ready(function() {
          function showOnly(clazz) {
            $('#tasks tbody tr:not(.' + clazz + ')').hide();
            $('#tasks tbody tr.' + clazz).show();
            return false;
          }
          function showAll() {
            $('#tasks tbody tr').show();
            return false;
          }

          $('table.sortable').tablesorter();
          $('#show-all').click(function() { showAll(); });
          $('#show-running').click(function() { showOnly('task-running'); });
          $('#show-successful').click(function() { showOnly('task-successful'); });
          $('#show-failed').click(function() { showOnly('task-failed'); });
          $('#show-timedout').click(function() { showOnly('task-timedout'); });
          $('#show-flaky').click(function() { showOnly('task-flaky'); });

          // Setup the lightbox for the "view" logs links
          $( "a.view" ).click(function() {
              $('#logModal .modal-title').text($(this).attr("viewheader"));
              $('#logModal .modal-body').load($(this).attr("viewlink"), function() {
                $('#logModal').modal();
              });
          });
        });
      </script>
    </body>
    </html>
    """)
    return template.render(body=body)


if __name__ == "__main__":
  config = Config()
  LOG = logging.getLogger('dist_test.server')
  dist_test.configure_logger(LOG, config.SERVER_LOG)

  LOG.info("Writing access logs to %s", config.SERVER_ACCESS_LOG)
  LOG.info("Writing error logs to %s", config.SERVER_ERROR_LOG)
  cherrypy.config.update({
    'server.socket_host': '0.0.0.0',
    'server.socket_port': 8081,
    'log.access_file': config.SERVER_ACCESS_LOG,
    'log.error_file': config.SERVER_ERROR_LOG,
  })
  LOG.info("Starting server")
  cherrypy.quickstart(DistTestServer(config))

