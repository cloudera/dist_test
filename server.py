#!/usr/bin/env python

import base64
import cherrypy
import datetime
import dist_test
import logging
import os
from jinja2 import Template
import urllib
import simplejson
import StringIO
import gzip
from collections import defaultdict

TRACE_HTML = os.path.join(os.path.dirname(__file__), "trace.html")

class DistTestServer(object):
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
  def job(self, job_id):
    tasks = self.results_store.fetch_task_rows_for_job(job_id)
    job_summary = self._summarize_tasks(tasks)
    body = ""
    body += self._render_job_header(job_id, job_summary)
    body += self._render_tasks(tasks, job_summary)
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
    simplejson.dump({"traceEvents": ret},
                    gzip.GzipFile(fileobj=trace_gz, mode="w"))
    trace_gz_b64 = base64.encodestring(trace_gz.getvalue())
    with open(TRACE_HTML, "r") as f:
      trace = f.read()
      trace = trace.replace("SUBSTITUTE_TRACE_HERE", trace_gz_b64)
    return trace

  @cherrypy.expose
  @cherrypy.tools.json_out()
  def cancel_job(self, job_id):
    self.results_store.cancel_job(job_id)
    return {"status": "SUCCESS"}

  @cherrypy.expose
  @cherrypy.tools.json_out()
  def submit_job(self, job_id, job_json):
    job_desc = simplejson.loads(job_json)

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
    job_summary = self._summarize_tasks(tasks, json_compatible=True)
    return job_summary

  @cherrypy.expose
  @cherrypy.tools.json_out()
  def failed_tasks(self, job_id):
    tasks = self.results_store.fetch_task_rows_for_job(job_id)
    ret = []
    for t in tasks:
      if t['status'] is not None and t['status'] != 0:
        record = dict(task_id=t['task_id'],
                      description=t['description'])
        if t['stdout_abbrev']:
          record['stdout_link'] = self.results_store.generate_output_link(t, "stdout")
        if t['stderr_abbrev']:
          record['stderr_link'] = self.results_store.generate_output_link(t, "stderr")
        ret.append(record)
    return ret

  def _summarize_tasks(self, tasks, json_compatible=False):
    """Computes aggregate statistics on a set of tasks.
    json_compatible kwarg is used to request JSON-compatible output, which is used by the client
    to report progress."""

    result = {}
    result['total_tasks'] = len(tasks)
    result['finished_tasks'] = len([1 for t in tasks if t['status'] is not None])
    result['running_tasks'] = len([1 for t in tasks if t['status'] is None])
    result['failed_tasks'] = len([1 for t in tasks if t['status'] is not None and t['status'] != 0])
    result['succeeded_tasks'] = len([1 for t in tasks if t['status'] == 0])
    result['timedout_tasks'] = len([1 for t in tasks if t['status'] == -9])

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

    return result

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

  def _render_job_header(self, job_id, job_summary):
    if job_summary['total_tasks'] > 0:
      success_percent = job_summary['succeeded_tasks'] * 100 / float(job_summary['total_tasks'])
      fail_percent = job_summary['failed_tasks'] * 100 / float(job_summary['total_tasks'])
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

  def _render_tasks(self, tasks, job_summary):
    for t in tasks:
      if t['stdout_abbrev']:
        t['stdout_link'] = self.results_store.generate_output_link(t, "stdout")
      if t['stderr_abbrev']:
        t['stderr_link'] = self.results_store.generate_output_link(t, "stderr")
      if t['complete_timestamp'] is not None:
        delta = t['complete_timestamp'] - t['start_timestamp']
        t['runtime'] = delta.seconds + (delta.days*24*60*60)

      elif t['start_timestamp'] is not None:
        delta = datetime.datetime.now() - t['start_timestamp']
        t['runtime'] = delta.seconds + (delta.days*24*60*60)
      else:
        t['runtime'] = None

    template = Template("""
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
} );
</script>
    <br style="clear: both;"/>
    <div>
      Show:
      <a id="show-all">all ({{ job_summary.total_tasks }})</a> |
      <a id="show-running">running ({{ job_summary.running_tasks }})</a> |
      <a id="show-failed">failed ({{ job_summary.failed_tasks }})</a> |
      <a id="show-successful">successful ({{ job_summary.succeeded_tasks }})</a> |
      <a id="show-timedout">timed out ({{ job_summary.timedout_tasks }})</a>
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
        <th>task</th>
      </tr>
    </thead>
    <tbody>
      {% for task in tasks %}
        <tr {% if task.status is none %}
              class="task-running"
            {% elif task.status == 0 %}
              class="task-successful"
            {% elif task.status == -9 %}
              class="task-failed task-timedout"
            {% else %}
              class="task-failed"
            {% endif %}>
          <td>{{ task.runtime | int |e }}</td>
          <td>{{ task.description |e }}</td>
          <td>{{ task.hostname |e }}</td>
          <td>{{ task.status |e }}</td>
          <td>{{ task.output_archive_hash |e }}</td>
          <td>{{ task.stdout_abbrev |e }}
              {% if task.stdout_link %}
              <a href="{{ task.stdout_link |e }}">download</a>
              {% endif %}
          </td>
          <td>{{ task.stderr_abbrev |e }}
              {% if task.stderr_link %}
              <a href="{{ task.stderr_link |e }}">download</a>
              {% endif %}
          </td>
          <td>{{ task.task_id |e }}</td>
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
        .filler.red { background-color: #f00; }
      </style>
    </head>
    <body>
      <script src="//ajax.googleapis.com/ajax/libs/jquery/1.11.1/jquery.min.js"></script>
      <script src="//maxcdn.bootstrapcdn.com/bootstrap/3.2.0/js/bootstrap.min.js"></script>
      <script src="//cdnjs.cloudflare.com/ajax/libs/jquery.tablesorter/2.18.2/js/jquery.tablesorter.min.js"></script>
      <div class="container-fluid">
      {{ body }}
      </div>
    </body>
    </html>
    """)
    return template.render(body=body)


if __name__ == "__main__":
  logging.basicConfig(level=logging.INFO)
  config = dist_test.Config()
  logging.info("Writing access logs to %s", config.ACCESS_LOG)
  logging.info("Writing error logs to %s", config.ERROR_LOG)
  cherrypy.config.update({
    'server.socket_host': '0.0.0.0',
    'server.socket_port': 8081,
    'log.access_file': config.ACCESS_LOG,
    'log.error_file': config.ERROR_LOG,
  })
  cherrypy.quickstart(DistTestServer(config))

