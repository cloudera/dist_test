# The lifecycle of a test task

Clients submit test *jobs* to the isolate server.
A *job* is composed of *tasks* which are individual unit tests.

Once the client has uploaded its dependencies and task descriptors to the isolate server, it submits a new job via the dist\_test server's REST API.
The server writes the task metadata to its backing MySQL database and then adds the tasks to the beanstalk queue.
Slaves pull tasks off of the beanstalk queue, and update the MySQL database when the task finishes.
When the task completes, the slave will upload any test artifacts that match the configured file patterns to S3, and if the task failed, will also upload the stdout and stderr output.
Tasks can also be configured with a number of retry attempts, to ride over flaky test failures. In this case, if the task still has retry attempts remaining, the slave will resubmit the task to the dist\_test server to rerun the task.

Meanwhile, the dist_test client is polling the server and printing job progress to stdout.
When the job finishes, the dist_test client can be used to download test artifacts and stdout/stderr output.

# Task scheduling

The dist_test server uses a mostly FIFO scheduling model, with a few optimizations.
The first optimization is that the server will sort the tasks by historical runtime, such that longer tasks are run first.
The second optimization is running retry tasks with boosted priority.
Together, these two methods have been effective at eliminating stragglers.

Implementing multiple queues with fair-share is a TODO.
However, this requires doing the queue management inside the dist\_test server rather than beanstalk, since beanstalk only supports a simple priority system.

# How to run a dist_task locally for debugging

When debugging a test failure, it's convenient to run the test locally for easy examination.

The first step is to find the hash that identifies the test task.
This is available on the master's job view in the **task** column, as the first component of a dot-delimited string (e.g. **000b7a003ff1d7eeb1cd1d0296e096079b03c0f5**.233).

Then, you can invoke Swarming's run\_isolated.py the same way as a dist\_test slave, using `--leak-temp-dir` to preserve the temp directory.

        $ export ISOLATE_SERVER=http://isolate.cloudera.org:4242
        $ ./swarming/client/run_isolated.py --verbose --leak-temp-dir --hash 000b7a003ff1d7eeb1cd1d0296e096079b03c0f5
        ...
        WARNING  22749    run_isolated(197): Deliberately leaking /tmp/run_tha_testGvhm8E for later examination

Now, poke around the `run_tha_test` dir in /tmp.
You can make changes to this local directory and retest by invoking the same command specified in your isolate file.

There is a grind-specific example in the [grind docs](grind.md) with more details.

# Slave auto-bursting

To save money, slaves can be bursted up and down based on demand.
This requires integration with your cloud provider.

We provide a `infra/gce-autoscale.py` script that can be used when running in Google Compute Engine.

# Authentication and authorization (server side)

The distributed test master has a very basic authentication and authorization system.
The master allows read-only access from anywhere, but requires authentication to
submit or cancel jobs. The authentication is done either by an IP whitelist or by
a username/password pair.

For example, to configure the server:

        [dist_test]
        allowed_ip_ranges=172.16.0.0/16
        accounts={"user1":"password", "user2":"pass"}

If a request originates from a host in the specified subnet, it will be allowed without
any user-based authentication. Otherwise, HTTP Digest authentication will be employed.

NOTE: slaves sometimes make requests back to the dist-test master. Thus, the slaves
must be configured with a username and password if they do not run from within an
allowed IP range.

# Authentication and authorization (client side)

If a client is not within an authorized IP range, its username and password can be
configured as follows:

        [dist_test]
        user=foo
        password=bar

Alternatively, the `DIST_TEST_USER` and `DIST_TEST_PASSWORD` environment variables may
be used to specify the credentials.
