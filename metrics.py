#!/usr/bin/python
import time
import json
import logging

from apiclient.discovery import build
import httplib2
from oauth2client.gce import AppAssertionCredentials

_CUSTOM_METRIC_DOMAIN = "custom.cloudmonitoring.googleapis.com"
_CUSTOM_METRIC_NAME = "%s/dist_test_slave_usage" % _CUSTOM_METRIC_DOMAIN

def _get_metadata():
  http = httplib2.Http()
  resp, content = http.request(
    "http://metadata.google.internal/computeMetadata/v1/?recursive=true",
    "GET", headers={"Metadata-Flavor": "Google"})
  if resp["status"] != "200":
    raise Exception("Unable to get project ID from metadata self.service.")
  return json.loads(content)

def _get_now_rfc3339():
  """Retrieve the current time formatted per RFC 3339."""
  return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

class MetricsCollector(object):
  """
  This class is responsible for submitting metrics to Google Cloud Monitoring.
  The metric that we submit as a simple 'business' metric -- the percentage
  of time that the slave was busy over a trailing time window. We then configure
  an auto-scaling managed instance group based on this metric so that if all
  of the slaves are consistently busy over this window, it starts more slaves.

  See https://cloud.google.com/compute/docs/autoscaler/
  In particular:
    https://cloud.google.com/compute/docs/autoscaler/scaling-cloud-monitoring-metrics
  """
  def __init__(self):
    credentials = AppAssertionCredentials(
        scope="https://www.googleapis.com/auth/monitoring")
    http = credentials.authorize(httplib2.Http())
    self.service = build(serviceName="cloudmonitoring", version="v2beta2", http=http)
    self.create_metric()
    
  def create_metric(self):
    """Create metric descriptor for the custom metric and send it to the API."""
    # You need to execute this operation only once. The operation is idempotent,
    # so, for simplicity, this sample code calls it each time

    # Create a label descriptor for each of the metric labels. The
    # "description" field should be more meaningful for your metrics.
    label_descriptors = [dict(key=n, description="built-in") for n in [
      'cloud.googleapis.com/service',
      'cloud.googleapis.com/location',
      'compute.googleapis.com/resource_type',
      'compute.googleapis.com/resource_id']]
    metadata = _get_metadata()
    project_id = metadata['project']['numericProjectId']
    # Create the metric descriptor for the custom metric.
    metric_descriptor = {
      "name": _CUSTOM_METRIC_NAME,
      "project": project_id,
      "typeDescriptor": {
        "metricType": "gauge",
        "valueType": "double",
      },
      "labels": label_descriptors,
      "description": "The usage of the dist test slave (1 = fully utilized).",
    }
    # Submit the custom metric creation request.
    try:
      request = self.service.metricDescriptors().create(
          project=project_id, body=metric_descriptor)
      _ = request.execute()  # ignore the response
    except Exception as e:
      print "Failed to create custom metric: exception=%s" % e
      raise  # propagate exception

  def submit(self, value):
    """Write a data point to a single time series of the custom metric."""
    logging.info("submitting value %s" % value)
    metadata = _get_metadata()
    project_id = metadata['project']['numericProjectId']
    zone  = metadata['instance']['zone'].rsplit('/', -1)[-1]
    # Identify the particular time series to which to write the data by
    # specifying the metric and values for each label.
    timeseries_descriptor = {
      "project": project_id,
      "metric": _CUSTOM_METRIC_NAME,
      "labels": {
        'cloud.googleapis.com/service': 'compute.googleapis.com',
        'cloud.googleapis.com/location': zone,
        'compute.googleapis.com/resource_type': 'instance',
        'compute.googleapis.com/resource_id': metadata['instance']['id'],
      }
    }
    # Specify a new data point for the time series.
    now_rfc3339 = _get_now_rfc3339()
    timeseries_data = {
      "timeseriesDesc": timeseries_descriptor,
      "point": {
        "start": now_rfc3339,
        "end": now_rfc3339,
        "doubleValue": value,
      }
    }
    # Submit the write request.
    request = self.service.timeseries().write(
        project=project_id, body={"timeseries": [timeseries_data,]})
    try:
      _ = request.execute()   # ignore the response
    except Exception as e:
      print "Failed to write data to custom metric: exception=%s" % e
      raise  # propagate exception


