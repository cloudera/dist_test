#!/usr/bin/env python

import base64
import cherrypy
import dist_test
import logging
import os
from jinja2 import Template
import simplejson
import StringIO
import gzip

TRACE_HTML = os.path.join(os.path.dirname(__file__), "trace.html")

class DistTestServer(object):
  def __init__(self):
    self.config = dist_test.Config()
    self.task_queue = dist_test.TaskQueue(self.config)
    self.results_store = dist_test.ResultsStore(self.config)

  @cherrypy.expose
  def index(self):
    stats = self.task_queue.stats()
    body = "<h1>Stats</h1>\n" + self._render_stats(stats)
    recent_tasks = self.results_store.fetch_recent_task_rows()
    body += "<h1>Recent tasks</h1>\n" + self._render_tasks(recent_tasks, None)
    return self.render_container(body)

  @cherrypy.expose
  def job(self, job_id):
    tasks = self.results_store.fetch_task_rows_for_job(job_id)
    job_summary = self._summarize_tasks(tasks)
    if job_summary['total_tasks'] > 0:
      success_percent = job_summary['succeeded_tasks'] * 100 / float(job_summary['total_tasks'])
      fail_percent = job_summary['failed_tasks'] * 100 / float(job_summary['total_tasks'])
    else:
      success_percent = 0
      fail_percent = 0
    body = "<h1>Job</h1>\n"
    body += """
    <div class="progress-bar">
      <div class="filler green" style="width: %.2f%%;"></div>
      <div class="filler red" style="width: %.2f%%;"></div>
    </div>""" % (
      success_percent, fail_percent)
    body += """
    <p>
    <a href="/trace?job_id=%s">Trace view</a>
    </p>
    """ % (job_id)
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
  def submit_tasks(self, job_id, tasks):
    if type(tasks) != list:
      tasks = [tasks]
    for isolate_hash in tasks:
      task = dist_test.Task.create(job_id, isolate_hash, "")
      self.results_store.register_task(task)
      self.task_queue.submit_task(task)
    return {"status": "SUCCESS"}

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

    self.results_store.register_tasks(tasks)
    for task in tasks:
      self.task_queue.submit_task(task)
    return {"status": "SUCCESS"}

  @cherrypy.expose
  @cherrypy.tools.json_out()
  def job_status(self, job_id):
    tasks = self.results_store.fetch_task_rows_for_job(job_id)
    job_summary = self._summarize_tasks(tasks)
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

  def _summarize_tasks(self, tasks):
    result = {}
    result['total_tasks'] = len(tasks)
    result['finished_tasks'] = len([1 for t in tasks if t['status'] is not None])
    result['running_tasks'] = len([1 for t in tasks if t['status'] is None])
    result['failed_tasks'] = len([1 for t in tasks if t['status'] is not None and t['status'] != 0])
    result['succeeded_tasks'] = len([1 for t in tasks if t['status'] == 0])
    result['timedout_tasks'] = len([1 for t in tasks if t['status'] == -9])
    return result

  def _render_stats(self, stats):
    template = Template("""
      <code>
        Queue length: {{ stats['current-jobs-ready'] }}
        Running: {{ stats['current-jobs-reserved'] }}
        Idle slaves: {{ stats['current-waiting'] }}
      </code>""")
    return template.render(stats=stats)

  def _render_tasks(self, tasks, job_summary):
    for t in tasks:
      if t['stdout_abbrev']:
        t['stdout_link'] = self.results_store.generate_output_link(t, "stdout")
      if t['stderr_abbrev']:
        t['stderr_link'] = self.results_store.generate_output_link(t, "stderr")

    # Generate an empty job summary if we weren't passed one
    if job_summary is None:
      job_summary = self._summarize_tasks([])

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
        <th>submit time</th>
        <th>start time</th>
        <th>complete time</th>
        <th>job</th>
        <th>task</th>
        <th>description</th>
        <th>hostname</th>
        <th>status</th>
        <th>results archive</th>
        <th>stdout</th>
        <th>stderr</th>
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
          <td>{{ task.submit_timestamp |e }}</td>
          <td>{{ task.start_timestamp |e }}</td>
          <td>{{ task.complete_timestamp |e }}</td>
          <td><a href="/job?job_id={{ task.job_id |urlencode }}">{{ task.job_id |e }}</a></td>
          <td>{{ task.task_id |e }}</td>
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
  logging.info("hello")
  cherrypy.config.update(
    {'server.socket_host': '0.0.0.0',
     'server.socket_port': 8081})
  cherrypy.quickstart(DistTestServer())

