#!/usr/bin/env python

import cherrypy
import dist_test
import logging
from jinja2 import Template
import simplejson

class DistTestServer(object):
  def __init__(self):
    self.config = dist_test.Config()
    self.task_queue = dist_test.TaskQueue(self.config)
    self.results_store = dist_test.ResultsStore(self.config)

  @cherrypy.expose
  def index(self):
    recent_tasks = self.results_store.fetch_recent_task_rows()
    body = "<h1>Recent tasks</h1>\n" + self._render_tasks(recent_tasks)
    return self.render_container(body)

  @cherrypy.expose
  def job(self, job_id):
    tasks = self.results_store.fetch_task_rows_for_job(job_id)
    body = "<h1>Job</h1>\n" + self._render_tasks(tasks)
    return self.render_container(body)

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
  def submit_job(self, job_id, job_json):
    job_desc = simplejson.loads(job_json)

    for task_desc in job_desc['tasks']:
      task = dist_test.Task.create(job_id,
                                   task_desc['isolate_hash'],
                                   task_desc.get('description', ''))
      self.results_store.register_task(task)
      self.task_queue.submit_task(task)
    return {"status": "SUCCESS"}

  @cherrypy.expose
  @cherrypy.tools.json_out()
  def job_status(self, job_id):
    tasks = self.results_store.fetch_task_rows_for_job(job_id)
    result = {}
    result['total_tasks'] = len(tasks)
    result['finished_tasks'] = len([1 for t in tasks if t['status'] is not None])
    result['failed_tasks'] = len([1 for t in tasks if t['status'] is not None and t['status'] != 0])
    result['succeeded_tasks'] = len([1 for t in tasks if t['status'] == 0])
    return result

  def _render_tasks(self, tasks):
    for t in tasks:
      if t['stdout_abbrev']:
        t['stdout_link'] = self.results_store.generate_output_link(t, "stdout")
      if t['stderr_abbrev']:
        t['stderr_link'] = self.results_store.generate_output_link(t, "stderr")

    template = Template("""
    <table class="table">
      <tr>
        <th>submit time</th>
        <th>complete time</th>
        <th>job</th>
        <th>task</th>
        <th>description</th>
        <th>status</th>
        <th>stdout</th>
        <th>stderr</th>
      </tr>
      {% for task in tasks %}
        <tr {% if task.status is none %}
              style="background-color: #ffa;"
            {% elif task.status == 0 %}
              style="background-color: #afa;"
            {% else %}
              style="background-color: #faa;"
            {% endif %}>
          <td>{{ task.submit_timestamp |e }}</td>
          <td>{{ task.complete_timestamp |e }}</td>
          <td>{{ task.job_id |e }}</td>
          <td>{{ task.task_id |e }}</td>
          <td>{{ task.description |e }}</td>
          <td>{{ task.status |e }}</td>
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
    </table>
    """)
    return template.render(tasks=tasks)

  def render_container(self, body):
    """ Render the "body" HTML inside of a bootstrap container page. """
    template = Template("""
    <!DOCTYPE html>
    <html>
      <head><title>Distributed Test Server</title>
      <link rel="stylesheet" href="//maxcdn.bootstrapcdn.com/bootstrap/3.2.0/css/bootstrap.min.css" />
      <style>
        .new-date { border-bottom: 2px solid #666; }
      </style>
    </head>
    <body>
      <script src="//ajax.googleapis.com/ajax/libs/jquery/1.11.1/jquery.min.js"></script>
      <script src="//maxcdn.bootstrapcdn.com/bootstrap/3.2.0/js/bootstrap.min.js"></script>
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

